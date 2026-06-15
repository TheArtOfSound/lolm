# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Daily Hugging Face ingestion — learn from the AI ecosystem, without rotting.

The strong version is NOT "download random datasets and train forever." It is:
daily ingest → score → license/quality/dedupe/poison filter → source-backed memory
(immediate, no weights touched) → a TRAINING-CANDIDATE QUEUE that is only ever
trained from behind an eval wall. This module is Layers 1-2 (memory + retrieval
learning, daily, real) plus the candidate queue feeding the GATED Layer-3 (weight
training, which never fires automatically — see hf_train.py).

Every ingest emits a receipt proving exactly what was seen, accepted, rejected
(and why), and written — and that ``model_weights_changed: false``. The hard rule:
do not claim LOLM "learns every day" beyond what this receipt can prove.

Uses the public Hugging Face Hub REST API (keyless) for dataset metadata incl.
license, tags, downloads, likes, gated. Injectable list_fn for offline tests.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lolm.research.memory import ResearchMemory, ResearchMemoryStore

# The categories LOLM actually wants — control behaviour, not raw tokens.
HF_TOPICS = [
    "reasoning", "agent trace", "tool use", "retrieval augmented", "grounded QA",
    "code review", "debugging", "formal logic", "math proof", "instruction following",
    "preference", "long context", "hallucination", "uncertainty calibration",
    "verifier", "fact checking",
]

# Commercial-OK permissive licenses (safe to train a commercial model from).
_COMMERCIAL_PREFIXES = ("apache", "mit", "bsd", "cc-by-4", "cc-by-sa-4", "cc0",
                        "odc-by", "odbl", "openrail", "bigscience-openrail",
                        "cc-by-3", "mpl", "isc", "unlicense")
_NONCOMMERCIAL = ("cc-by-nc", "cc-nc", "noncommercial")
_COPYLEFT = ("gpl", "agpl", "lgpl")
# Tags / ids that flag poison / unsafe-for-LOLM-goals content.
_POISON = ("nsfw", "not-for-all-audiences", "toxic", "jailbreak", "uncensored",
           "roleplay-nsfw", "erotica", "gore")


def classify_license(lic: Optional[str]) -> str:
    """commercial_ok | noncommercial | copyleft | custom | unknown."""
    l = (lic or "").lower().strip()
    if not l or l in ("unknown", "other", "unlicense-unknown", "none"):
        return "unknown"
    if any(k in l for k in _NONCOMMERCIAL):
        return "noncommercial"
    if l.startswith(_COMMERCIAL_PREFIXES):
        return "commercial_ok"
    if any(k in l for k in _COPYLEFT):
        return "copyleft"
    return "custom"


def hf_list_datasets(topic: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Public HF Hub REST API — keyless dataset metadata, sorted by downloads."""
    import requests
    r = requests.get("https://huggingface.co/api/datasets",
                     params={"search": topic, "limit": limit, "full": "true",
                             "sort": "downloads", "direction": -1},
                     headers={"User-Agent": "LOLM-NFET/1.0 (research ingestor)"},
                     timeout=20)
    r.raise_for_status()
    return r.json()


def _meta(d: Dict[str, Any]) -> Dict[str, Any]:
    cd = d.get("cardData") or {}
    lic = cd.get("license") or d.get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    return {
        "repo_id": d.get("id", ""), "downloads": int(d.get("downloads", 0) or 0),
        "likes": int(d.get("likes", 0) or 0), "gated": bool(d.get("gated")),
        "license": lic, "tags": [str(t).lower() for t in (d.get("tags") or [])],
        "has_card": bool(cd), "last_modified": d.get("lastModified"),
        "description": (cd.get("pretty_name") or d.get("description") or d.get("id", ""))[:300],
    }


def quality_score(m: Dict[str, Any]) -> float:
    """0..1 from downloads, likes, card presence, tag richness."""
    import math
    dl = math.log10(m["downloads"] + 1) / 5.0          # ~1.0 at 100k downloads
    lk = math.log10(m["likes"] + 1) / 3.0              # ~1.0 at 1k likes
    card = 0.2 if m["has_card"] else 0.0
    tags = min(len(m["tags"]) / 20.0, 0.2)
    return round(min(1.0, 0.45 * dl + 0.3 * lk + card + tags), 4)


def poison_flags(m: Dict[str, Any]) -> List[str]:
    blob = (m["repo_id"] + " " + " ".join(m["tags"])).lower()
    return [p for p in _POISON if p in blob]


def relevant_topic(m: Dict[str, Any], topics: List[str]) -> Optional[str]:
    blob = (m["repo_id"] + " " + " ".join(m["tags"]) + " " + m["description"]).lower()
    for t in topics:
        if all(w in blob for w in t.split()):
            return t
    return None


class TrainingCandidateQueue:
    """Durable queue of training candidates. Queued != trained — Layer 3 is gated."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def add(self, cand: Dict[str, Any]) -> str:
        cid = cand.get("candidate_id") or f"cand_{uuid.uuid4().hex[:12]}"
        cand = {**cand, "candidate_id": cid, "trained": False}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(cand, ensure_ascii=False) + "\n")
        return cid

    def all(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            with self.path.open() as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        return rows

    def stats(self) -> Dict[str, Any]:
        rows = self.all()
        return {"total": len(rows), "untrained": sum(1 for r in rows if not r.get("trained")),
                "by_topic": _counts(r.get("topic") for r in rows)}


def _counts(it) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in it:
        if x:
            out[x] = out.get(x, 0) + 1
    return out


@dataclass
class IngestResult:
    receipt: Dict[str, Any]
    memories_written: List[str] = field(default_factory=list)
    candidates_queued: List[str] = field(default_factory=list)


def ingest(*, memory_store: ResearchMemoryStore, queue: TrainingCandidateQueue,
           list_fn: Callable[[str, int], List[Dict[str, Any]]] = hf_list_datasets,
           topics: Optional[List[str]] = None, per_topic: int = 12,
           min_quality: float = 0.25, min_train_quality: float = 0.45,
           now: Optional[float] = None) -> IngestResult:
    """Scan HF for relevant datasets, filter, learn into memory, queue candidates."""
    topics = topics or HF_TOPICS
    seen_ids: set = set()
    reasons = {"irrelevant": 0, "gated_or_unapproved": 0, "low_quality": 0,
               "duplicate": 0, "unknown_license": 0, "noncommercial": 0,
               "poison_flagged": 0, "copyleft_or_custom": 0}
    seen = relevant = accepted = 0
    mems: List[str] = []
    cands: List[str] = []
    licenses_seen: Dict[str, int] = {}

    for topic in topics:
        try:
            rows = list_fn(topic, per_topic) or []
        except Exception:
            continue
        for d in rows:
            m = _meta(d)
            rid = m["repo_id"]
            if not rid or rid in seen_ids:
                if rid:
                    reasons["duplicate"] += 1
                continue
            seen_ids.add(rid)
            seen += 1
            topic_hit = relevant_topic(m, topics)
            if not topic_hit:
                reasons["irrelevant"] += 1
                continue
            relevant += 1
            lic_class = classify_license(m["license"])
            licenses_seen[m["license"] or "unknown"] = licenses_seen.get(m["license"] or "unknown", 0) + 1
            flags = poison_flags(m)
            q = quality_score(m)

            # Hard rejects (no memory either): gated, poisoned.
            if m["gated"]:
                reasons["gated_or_unapproved"] += 1
                continue
            if flags:
                reasons["poison_flagged"] += 1
                continue
            if q < min_quality:
                reasons["low_quality"] += 1
                continue

            # Relevant + clean enough → LEARN a source-backed memory (license recorded).
            url = f"https://huggingface.co/datasets/{rid}"
            train_ok = (lic_class == "commercial_ok" and q >= min_train_quality)
            if lic_class == "unknown":
                reasons["unknown_license"] += 1
            elif lic_class == "noncommercial":
                reasons["noncommercial"] += 1
            elif lic_class in ("copyleft", "custom"):
                reasons["copyleft_or_custom"] += 1

            mem = ResearchMemory(
                topic=f"HF dataset · {topic_hit}",
                claim=f"{rid}: {m['description'][:160]}",
                summary=(f"Hugging Face dataset for {topic_hit}. license={m['license'] or 'unknown'} "
                         f"({lic_class}), downloads={m['downloads']}, likes={m['likes']}, "
                         f"quality={q}. training_candidate={train_ok}."),
                source_urls=[url], source_titles=[rid],
                source_quality="high" if q >= 0.6 else "medium",
                confidence=q, staleness_policy="30d",
                review_status="auto" if train_ok else "needs_human_review",
                risk_level="low" if lic_class == "commercial_ok" else "medium",
                tags=["huggingface", topic_hit, f"license:{lic_class}",
                      "training_candidate" if train_ok else "memory_only"])
            mems.append(memory_store.write(mem))

            if train_ok:
                accepted += 1
                cands.append(queue.add({
                    "repo_id": rid, "url": url, "license": m["license"],
                    "license_class": lic_class, "topic": topic_hit, "quality": q,
                    "candidate_type": "dataset", "downloads": m["downloads"],
                    "queued_at": _iso(now), "source_memory": mems[-1]}))

    receipt = {
        "ingest_id": f"hfingest_{uuid.uuid4().hex[:10]}",
        "ingest_date": _iso(now)[:10], "source": "huggingface",
        "topics_scanned": len(topics),
        "datasets_seen": seen, "datasets_relevant": relevant,
        "datasets_rejected": seen - relevant + sum(reasons[k] for k in
                              ("gated_or_unapproved", "low_quality", "poison_flagged")),
        "rejection_reasons": reasons, "licenses_seen": licenses_seen,
        "datasets_accepted": accepted, "memories_written": len(mems),
        "training_examples_queued": len(cands),
        "adapters_trained": 0, "model_weights_changed": False,
        "qev_sealed": False,
        "note": ("Memory + candidate queue updated; NO model weights changed. "
                 "Weight training is gated behind the eval harness (hf_train) and "
                 "does not run automatically."),
    }
    return IngestResult(receipt=receipt, memories_written=mems, candidates_queued=cands)


def _iso(now: Optional[float]) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now else time.time()))
