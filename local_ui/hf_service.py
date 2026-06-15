# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Hugging Face daily-learning service — wires the ingestor into the live demo.

Layers, honestly separated:
  L1 memory     — every relevant, clean dataset becomes a source-backed memory NOW.
  L2 retrieval  — those memories are queryable; the candidate queue is the index.
  L3 weights    — GATED. Candidates queue up; weights change only behind the eval
                  wall (hf_train), never on autopilot, never on this CPU box.

Persists an ingest receipt per run, a candidate queue, and a dedicated HF memory
store, then serves a dashboard that proves exactly what was learned — and that
``model_weights_changed: false``. Runs one ingest per day in a bounded daemon
thread; a manual trigger exists but is rate-limited and capped.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lolm.research.memory import ResearchMemoryStore
from lolm.research import hf_ingest as hi
from lolm.research.hf_train import TrainingPipeline


def _detect_gpu() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available() or
                    getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except Exception:
        return False


class HFLearningService:
    def __init__(self, state_dir: str | Path, *, per_topic: int = 8,
                 daily_topics: Optional[List[str]] = None,
                 check_interval: float = 1800.0, first_delay: float = 120.0):
        self.state_dir = Path(state_dir)
        self.memory = ResearchMemoryStore(self.state_dir / "hf_memory.jsonl")
        self.queue = hi.TrainingCandidateQueue(self.state_dir / "hf_candidates.jsonl")
        self.training = TrainingPipeline(self.queue, has_gpu=_detect_gpu())
        self.receipts_path = self.state_dir / "hf_ingest_receipts.jsonl"
        self.latest_path = self.state_dir / "hf_ingest_latest.json"
        self.meta_path = self.state_dir / "hf_ingest_meta.json"
        self.per_topic = per_topic
        self.daily_topics = daily_topics  # None → full HF_TOPICS list
        self.check_interval = check_interval
        self.first_delay = first_delay
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_ingest_at = self._load_meta().get("last_ingest_at", 0.0)

    # -- persistence ---------------------------------------------------------
    def _load_meta(self) -> Dict[str, Any]:
        try:
            return json.loads(self.meta_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_meta(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps({"last_ingest_at": self._last_ingest_at}))

    def _persist(self, receipt: Dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.receipts_path.open("a") as f:
            f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        self.latest_path.write_text(json.dumps(receipt, indent=2))

    def recent_receipts(self, limit: int = 30) -> List[Dict[str, Any]]:
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

    # -- ingest --------------------------------------------------------------
    def run_ingest(self, topics: Optional[List[str]] = None,
                   per_topic: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            res = hi.ingest(memory_store=self.memory, queue=self.queue,
                            topics=topics or self.daily_topics,
                            per_topic=per_topic or self.per_topic)
            self._last_ingest_at = time.time()
            self._save_meta()
            self._persist(res.receipt)
        return res.receipt

    # -- background daily loop ----------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hf-ingest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # First-ever ingest after a short delay so the dashboard isn't empty.
        if self._stop.wait(self.first_delay):
            return
        while True:
            try:
                if time.time() - self._last_ingest_at >= 86_400:
                    self.run_ingest()
            except Exception:
                pass  # a flaky network must never kill the daemon
            if self._stop.wait(self.check_interval):
                return

    # -- dashboard -----------------------------------------------------------
    def dashboard(self) -> Dict[str, Any]:
        receipts = self.recent_receipts(60)
        totals = {
            "ingests": len(receipts),
            "datasets_seen": sum(r.get("datasets_seen", 0) for r in receipts),
            "datasets_accepted": sum(r.get("datasets_accepted", 0) for r in receipts),
            "memories_written": sum(r.get("memories_written", 0) for r in receipts),
            "candidates_queued": sum(r.get("training_examples_queued", 0) for r in receipts),
            "adapters_trained": sum(r.get("adapters_trained", 0) for r in receipts),
        }
        latest = None
        try:
            latest = json.loads(self.latest_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return {
            "latest_ingest": latest,
            "totals": totals,
            "model_weights_changed_ever": False,
            "memory_stats": self.memory.stats(),
            "candidate_stats": self.queue.stats(),
            "training": self.training.status(),
            "recent_receipts": receipts[-12:],
            "honest_claim": (
                "LOLM ingests the AI dataset ecosystem daily, writes source-backed "
                "memories with license + quality recorded, and queues training "
                "candidates — but promotes model weights only when an eval proves "
                "improvement. No weights have changed automatically."),
        }


def make_hf_service(state_dir: str | Path, **kw) -> HFLearningService:
    return HFLearningService(state_dir, **kw)


def register_hf_routes(app: Any, service: HFLearningService,
                       gate: Optional[Any] = None) -> None:

    @app.get("/api/demo/hf/dashboard")
    def hf_dashboard():
        return service.dashboard()

    @app.get("/api/demo/hf/candidates")
    def hf_candidates():
        rows = service.queue.all()
        return {"count": len(rows), "untrained": sum(1 for r in rows if not r.get("trained")),
                "candidates": [{"repo_id": c.get("repo_id"), "license": c.get("license"),
                                "topic": c.get("topic"), "quality": c.get("quality"),
                                "url": c.get("url")} for c in rows[-40:]]}

    @app.post("/api/demo/hf/ingest")
    def hf_ingest_now():
        if gate is not None and hasattr(gate, "check_rate"):
            ok, msg = gate.check_rate("hf_ingest")
            if not ok:
                return {"error": msg, "rate_limited": True}
        # Public manual trigger is capped so it can't hammer the HF API.
        topics = hi.HF_TOPICS[:4]
        try:
            return service.run_ingest(topics=topics, per_topic=6)
        except Exception as exc:
            return {"error": f"ingest failed: {exc}"[:300]}

    @app.get("/api/demo/hf/training")
    def hf_training():
        return {"status": service.training.status(),
                "dry_run_plan": service.training.dry_run_plan()}
