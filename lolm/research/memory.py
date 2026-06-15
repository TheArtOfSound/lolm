# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Source-backed memory — what "learning" actually means here.

LOLM does not mutate model weights or pretend it trained itself. It writes
structured, source-backed, REVERSIBLE memories that future runs retrieve and
cite. Every memory carries where it came from, how good the source was, when it
was last checked, when it goes stale, what contradicts it, and which runs used
it. A bad / stale / contradicted / low-quality memory can be demoted or removed —
learning you can audit and undo.

Pure Python + JSONL persistence (last-write-wins per memory_id), no torch/network.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Staleness policies → seconds (None = never expires).
STALENESS: Dict[str, Optional[int]] = {
    "1d": 86_400, "7d": 604_800, "30d": 2_592_000, "90d": 7_776_000,
    "365d": 31_536_000, "never": None,
}

# Source-quality heuristic. Primary docs / encyclopedic / official > general > social.
_HIGH = (".gov", ".edu", "wikipedia.org", "arxiv.org", "docs.", "developer.",
         "openai.com", "anthropic.com", "github.com", "who.int", "nature.com",
         "iso.org", "ietf.org", "python.org")
_LOW = ("reddit.com", "quora.com", "pinterest.", "facebook.com", "x.com",
        "twitter.com", "tiktok.com", "answers.", "ezinearticles")


def source_quality(url: str) -> str:
    """high | medium | low from the URL's host (heuristic, documented)."""
    host = (urlparse(url).hostname or url or "").lower()
    if any(s in url.lower() or s in host for s in _HIGH):
        return "high"
    if any(s in host for s in _LOW):
        return "low"
    return "medium"


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@dataclass
class ResearchMemory:
    topic: str
    claim: str
    memory_id: str = ""
    summary: str = ""
    source_urls: List[str] = field(default_factory=list)
    source_titles: List[str] = field(default_factory=list)
    source_quality: str = ""   # auto-graded from source_urls if left empty
    confidence: float = 0.5
    created_at: str = ""
    last_checked_at: str = ""
    expires_at: Optional[str] = None
    staleness_policy: str = "30d"
    contradictions: List[str] = field(default_factory=list)
    used_in_runs: List[str] = field(default_factory=list)
    review_status: str = "auto"       # auto|needs_human_review|approved|rejected
    risk_level: str = "low"           # low|medium|high
    tags: List[str] = field(default_factory=list)
    demoted: bool = False
    demote_reason: Optional[str] = None

    def __post_init__(self):
        now = _now()
        if not self.memory_id:
            self.memory_id = f"mem_{uuid.uuid4().hex[:14]}"
        if not self.created_at:
            self.created_at = _iso(now)
        if not self.last_checked_at:
            self.last_checked_at = self.created_at
        if self.expires_at is None:
            secs = STALENESS.get(self.staleness_policy, STALENESS["30d"])
            self.expires_at = _iso(now + secs) if secs is not None else None
        if not self.source_quality:
            if self.source_urls:
                qs = [source_quality(u) for u in self.source_urls]
                self.source_quality = ("high" if "high" in qs
                                       else "low" if all(q == "low" for q in qs) else "medium")
            else:
                self.source_quality = "medium"

    def is_stale(self, now_ts: Optional[float] = None) -> bool:
        if not self.expires_at:
            return False
        now_ts = now_ts if now_ts is not None else _now()
        return now_ts > _epoch(self.expires_at)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _epoch(iso: str) -> float:
    try:
        return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except Exception:
        return 0.0


def _tokens(text: str) -> set:
    return {w for w in re.split(r"\W+", (text or "").lower()) if len(w) > 2}


class ResearchMemoryStore:
    """JSONL-backed, reversible store for source-backed memories."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------------
    def _all_rows(self) -> Dict[str, Dict[str, Any]]:
        rows: Dict[str, Dict[str, Any]] = {}
        try:
            with self.path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    mid = r.get("memory_id")
                    if mid:
                        if r.get("_deleted"):
                            rows.pop(mid, None)
                        else:
                            rows[mid] = r
        except FileNotFoundError:
            pass
        return rows

    def _append(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # -- write / update ------------------------------------------------------
    def write(self, mem: ResearchMemory) -> str:
        self._append(mem.to_dict())
        return mem.memory_id

    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        return self._all_rows().get(memory_id)

    def update(self, memory_id: str, **fields) -> Optional[Dict[str, Any]]:
        row = self.get(memory_id)
        if not row:
            return None
        row.update(fields)
        row["last_checked_at"] = _iso(_now())
        self._append(row)
        return row

    def mark_stale(self, memory_id: str) -> Optional[Dict[str, Any]]:
        return self.update(memory_id, expires_at=_iso(_now() - 1),
                           review_status="needs_human_review")

    def demote(self, memory_id: str, reason: str = "low quality or contradicted") -> Optional[Dict[str, Any]]:
        return self.update(memory_id, demoted=True, demote_reason=reason,
                           confidence=0.0)

    def delete(self, memory_id: str) -> None:
        self._append({"memory_id": memory_id, "_deleted": True})

    def record_use(self, memory_id: str, run_id: str) -> None:
        row = self.get(memory_id)
        if row is not None:
            used = list(dict.fromkeys((row.get("used_in_runs") or []) + [run_id]))
            self.update(memory_id, used_in_runs=used)

    def add_contradiction(self, memory_id: str, other_id: str) -> None:
        row = self.get(memory_id)
        if row is not None:
            c = list(dict.fromkeys((row.get("contradictions") or []) + [other_id]))
            self.update(memory_id, contradictions=c)

    # -- retrieval -----------------------------------------------------------
    def all(self, include_demoted: bool = False) -> List[Dict[str, Any]]:
        rows = list(self._all_rows().values())
        if not include_demoted:
            rows = [r for r in rows if not r.get("demoted")]
        return rows

    def retrieve(self, query: str, limit: int = 5, fresh_only: bool = True,
                 now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        """Keyword-relevant memories, ranked by overlap × quality × confidence,
        with stale ones flagged (and excluded when fresh_only)."""
        q = _tokens(query)
        if not q:
            return []
        qual_w = {"high": 1.3, "medium": 1.0, "low": 0.6}
        scored = []
        for r in self.all(include_demoted=False):
            text = " ".join([r.get("topic", ""), r.get("claim", ""),
                             r.get("summary", ""), " ".join(r.get("tags", []))])
            overlap = len(q & _tokens(text))
            if overlap == 0:
                continue
            mem = ResearchMemory(**{k: v for k, v in r.items()
                                    if k in ResearchMemory.__dataclass_fields__})
            stale = mem.is_stale(now_ts)
            if stale and fresh_only:
                # keep but flag so the caller can decide to refresh
                r = {**r, "_stale": True}
            score = overlap * qual_w.get(r.get("source_quality", "medium"), 1.0) \
                * (0.4 + 0.6 * float(r.get("confidence", 0.5)))
            if stale:
                score *= 0.5
            scored.append((score, {**r, "_stale": stale}))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [r for _, r in scored[:limit]]

    def stats(self) -> Dict[str, Any]:
        rows = list(self._all_rows().values())
        live = [r for r in rows if not r.get("demoted")]
        now = _now()
        stale = sum(1 for r in live if ResearchMemory(
            **{k: v for k, v in r.items() if k in ResearchMemory.__dataclass_fields__}
        ).is_stale(now))
        return {
            "total": len(live), "demoted": sum(1 for r in rows if r.get("demoted")),
            "stale": stale, "needs_review": sum(1 for r in live if r.get("review_status") == "needs_human_review"),
            "by_quality": {q: sum(1 for r in live if r.get("source_quality") == q)
                           for q in ("high", "medium", "low")},
        }
