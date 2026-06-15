# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Background research jobs — LOLM learns without a live prompt.

A job is a real object: a topic, a schedule, a query plan, and a memory-write
policy. Running it searches the live web, opens and ranks sources, extracts
claims, writes source-backed memories future runs can reuse, flags potential
source conflicts, and emits a job receipt. Findings that match a job's
``notify_on`` triggers are surfaced as high-impact.

Injectable search_fn / fetch_fn so jobs are testable offline; in production they
are the same internet_tools providers the live research pipeline uses.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

from lolm.research.memory import ResearchMemory, ResearchMemoryStore, source_quality
from lolm.research.pipeline import unwrap_url, _best_sentence, _toks


@dataclass
class ResearchJob:
    topic: str
    queries: List[str]
    job_id: str = ""
    schedule: str = "daily"            # daily | weekly | hourly | manual
    max_sources: int = 8
    memory_write: bool = True
    human_review_required: bool = False
    notify_on: List[str] = field(default_factory=list)
    enabled: bool = True
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    status: str = "idle"

    def __post_init__(self):
        if not self.job_id:
            slug = "_".join(self.topic.lower().split()[:5])
            self.job_id = f"research_{slug}_{self.schedule}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# The required watch topics, as real default jobs.
def default_jobs() -> List[ResearchJob]:
    specs = [
        ("AI agent receipts and verifiable run logs",
         ["AI agent audit trail run receipt", "verifiable AI agent logs",
          "AI coding agent trace receipt"], ["new competitor", "new paper", "major claim change"]),
        ("uncertainty calibration for language models",
         ["LLM uncertainty calibration retrieval agent", "selective prediction LLM calibration"],
         ["new paper", "major claim change"]),
        ("retrieval-augmented generation failures",
         ["RAG failure modes", "retrieval augmented generation hallucination"], ["new paper"]),
        ("AI agent tool-use verification",
         ["agent tool use verification", "LLM tool call outcome verification"], ["new paper"]),
        ("OpenAI Anthropic Claude Codex agent capabilities",
         ["Claude Code agent capabilities official docs", "OpenAI agents API capabilities"],
         ["major claim change", "security-relevant finding"]),
        ("LOLM NFET competitors and cryptographic receipt systems",
         ["AI run receipt competitor", "cryptographic AI provenance receipt"],
         ["new competitor", "security-relevant finding"]),
        ("verifiable AI logs and model self-checking systems",
         ["verifiable AI logs", "LLM self-verification self-check"], ["new paper"]),
        ("autonomous research agents",
         ["autonomous research agent web search", "AI deep research agent"], ["new competitor"]),
    ]
    return [ResearchJob(topic=t, queries=q, notify_on=n) for t, q, n in specs]


def _detect_conflicts(opened: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flag pairs of sources whose claims barely overlap (potential disagreement)."""
    conflicts = []
    for i in range(len(opened)):
        for j in range(i + 1, len(opened)):
            a, b = opened[i].get("claim", ""), opened[j].get("claim", "")
            ta, tb = _toks(a), _toks(b)
            if ta and tb:
                overlap = len(ta & tb) / max(min(len(ta), len(tb)), 1)
                if overlap < 0.12:
                    conflicts.append({"a": opened[i]["url"], "b": opened[j]["url"],
                                      "overlap": round(overlap, 3)})
    return conflicts[:5]


def run_job(job: ResearchJob, *, search_fn: Callable, fetch_fn: Optional[Callable],
            memory_store: ResearchMemoryStore, now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Execute one research job → write memories → job receipt."""
    run_id = f"job-{uuid.uuid4().hex[:12]}"
    retrieved: List[Dict[str, Any]] = []
    opened: List[Dict[str, Any]] = []
    written: List[str] = []
    errors: List[str] = []

    for q in job.queries:
        try:
            res = search_fn(q, min(job.max_sources, 8)) or {}
        except Exception as exc:
            errors.append(f"search '{q}': {exc}"[:120]); continue
        for r in (res.get("results") or []):
            retrieved.append({"title": r.get("title", ""), "url": unwrap_url(r.get("url", "")),
                              "snippet": r.get("snippet", ""), "query": q})

    # Rank by source quality, open the best few.
    seen, uniq = set(), []
    for r in retrieved:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"]); uniq.append(r)
    qual = {"high": 1.5, "medium": 1.0, "low": 0.4}
    uniq.sort(key=lambda r: qual.get(source_quality(r["url"]), 1.0), reverse=True)

    for r in uniq[: job.max_sources]:
        text = r.get("snippet", "")
        if fetch_fn is not None:
            try:
                f = fetch_fn(r["url"]) or {}
                text = f.get("text") or text
            except Exception as exc:
                errors.append(f"fetch {r['url']}: {exc}"[:120])
        claim = _best_sentence(text, job.topic) or r.get("snippet", "")
        opened.append({**r, "claim": claim, "quality": source_quality(r["url"])})

    conflicts = _detect_conflicts(opened)

    if job.memory_write:
        for s in opened:
            if s["quality"] == "low" or not s["claim"]:
                continue
            mem = ResearchMemory(
                topic=job.topic, claim=s["claim"][:300],
                summary=s["claim"][:300], source_urls=[s["url"]],
                source_titles=[s.get("title", "")], confidence=0.6,
                review_status="needs_human_review" if job.human_review_required else "auto",
                tags=[job.job_id], used_in_runs=[run_id])
            written.append(memory_store.write(mem))

    high_impact = []
    if job.notify_on:
        blob = " ".join(s.get("title", "") + " " + s.get("claim", "") for s in opened).lower()
        for trig in job.notify_on:
            key = trig.split()[-1].lower()
            if key in blob:
                high_impact.append(trig)

    job.last_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(now_ts if now_ts else time.time()))
    job.status = "ok" if not errors else "partial"
    return {
        "job_id": job.job_id, "topic": job.topic, "ran_at": job.last_run_at,
        "queries": job.queries, "sources_checked": len(retrieved),
        "sources_opened": len(opened), "memories_written": written,
        "conflicts": conflicts, "high_impact": high_impact,
        "status": "ok" if not errors else ("failed" if not opened else "partial"),
        "errors": errors,
    }
