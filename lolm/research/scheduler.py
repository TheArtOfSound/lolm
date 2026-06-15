# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Background research scheduler — LOLM learns while nobody is watching.

Runs research jobs on a cadence (daily / hourly / weekly), writes source-backed
memories, and persists both job state (last/next run, status) and a receipt per
run. A bounded daemon thread executes at most one job per check so it never
hammers the search provider; initial runs are staggered so memory fills in
gradually rather than all at once.

This is the difference between "we have job objects" and "the system is actually
learning in the background." It is the latter.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lolm.research.jobs import ResearchJob, run_job, default_jobs
from lolm.research.memory import ResearchMemoryStore

_INTERVAL = {"hourly": 3600, "daily": 86_400, "weekly": 604_800, "manual": None}


class ResearchScheduler:
    def __init__(self, jobs: List[ResearchJob], *, search_fn: Callable,
                 fetch_fn: Optional[Callable], memory_store: ResearchMemoryStore,
                 state_dir: str | Path, check_interval: float = 300.0,
                 max_per_check: int = 1, first_delay: float = 45.0,
                 stagger: float = 600.0):
        self.jobs: Dict[str, ResearchJob] = {j.job_id: j for j in jobs}
        self.search_fn = search_fn
        self.fetch_fn = fetch_fn
        self.memory_store = memory_store
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / "research_jobs_state.json"
        self.receipts_path = self.state_dir / "research_job_receipts.jsonl"
        self.check_interval = check_interval
        self.max_per_check = max_per_check
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._load_state()
        # Stagger first runs for jobs that have never run.
        now = time.time()
        for i, job in enumerate(j for j in self.jobs.values() if not j.last_run_at):
            self._next_run[job.job_id] = now + first_delay + i * stagger

    # -- persistence ---------------------------------------------------------
    def _load_state(self) -> None:
        self._next_run: Dict[str, float] = {}
        try:
            data = json.loads(self.state_path.read_text())
            for jid, st in data.get("jobs", {}).items():
                if jid in self.jobs:
                    self.jobs[jid].last_run_at = st.get("last_run_at")
                    self.jobs[jid].status = st.get("status", "idle")
                    self.jobs[jid].enabled = st.get("enabled", True)
                    if st.get("next_run"):
                        self._next_run[jid] = float(st["next_run"])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "jobs": {jid: {"last_run_at": j.last_run_at, "status": j.status,
                           "enabled": j.enabled, "next_run": self._next_run.get(jid)}
                     for jid, j in self.jobs.items()}}, indent=2))

    def _append_receipt(self, rcpt: Dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.receipts_path.open("a") as f:
            f.write(json.dumps(rcpt, ensure_ascii=False) + "\n")

    # -- scheduling ----------------------------------------------------------
    def due(self, now_ts: Optional[float] = None) -> List[ResearchJob]:
        now = now_ts if now_ts is not None else time.time()
        out = []
        for jid, job in self.jobs.items():
            if not job.enabled or job.schedule == "manual":
                continue
            if now >= self._next_run.get(jid, 0):
                out.append(job)
        return out

    def run_job_now(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        with self._lock:
            rcpt = run_job(job, search_fn=self.search_fn, fetch_fn=self.fetch_fn,
                           memory_store=self.memory_store)
            interval = _INTERVAL.get(job.schedule)
            if interval:
                self._next_run[job_id] = time.time() + interval
            self._append_receipt(rcpt)
            self._save_state()
        return rcpt

    def run_due(self, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        ran = []
        for job in self.due(now_ts)[: self.max_per_check]:
            r = self.run_job_now(job.job_id)
            if r:
                ran.append(r)
        return ran

    # -- background loop -----------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="research-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.check_interval):
            try:
                self.run_due()
            except Exception:
                pass  # a flaky network must never kill the scheduler

    # -- control / status ----------------------------------------------------
    def pause(self, job_id: str) -> bool:
        if job_id in self.jobs:
            self.jobs[job_id].enabled = False
            self._save_state()
            return True
        return False

    def resume(self, job_id: str) -> bool:
        if job_id in self.jobs:
            self.jobs[job_id].enabled = True
            self._save_state()
            return True
        return False

    def recent_receipts(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            with self.receipts_path.open() as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        return rows[-limit:]

    def status(self) -> Dict[str, Any]:
        now = time.time()
        jobs = []
        for jid, j in self.jobs.items():
            nxt = self._next_run.get(jid)
            jobs.append({
                "job_id": jid, "topic": j.topic, "schedule": j.schedule,
                "enabled": j.enabled, "status": j.status, "last_run_at": j.last_run_at,
                "next_run_in_sec": round(nxt - now) if nxt else None,
                "queries": j.queries, "notify_on": j.notify_on,
            })
        receipts = self.recent_receipts(50)
        return {
            "jobs": jobs,
            "running": bool(self._thread and self._thread.is_alive()),
            "total_runs": len(receipts),
            "memories_written_total": sum(len(r.get("memories_written", [])) for r in receipts),
            "high_impact": [{"job_id": r["job_id"], "findings": r["high_impact"], "at": r.get("ran_at")}
                            for r in receipts if r.get("high_impact")][-10:],
            "memory_stats": self.memory_store.stats(),
        }


def build_scheduler(search_fn: Callable, fetch_fn: Optional[Callable],
                    memory_store: ResearchMemoryStore, state_dir: str | Path,
                    **kw) -> ResearchScheduler:
    return ResearchScheduler(default_jobs(), search_fn=search_fn, fetch_fn=fetch_fn,
                             memory_store=memory_store, state_dir=state_dir, **kw)
