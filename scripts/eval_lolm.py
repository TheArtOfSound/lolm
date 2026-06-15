#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Fast, CPU-only LOLM behaviour eval — the wall the daily agent must clear.

Three real sub-evals of the decision logic that ships in the controller, no GPU
or 70B needed, fully deterministic:

  controller  — search-decision accuracy on labelled prompts (search vs. answer)
  retrieval   — memory retrieval flags staleness correctly (fresh vs. expired)
  license     — HF license classifier puts datasets in the right commercial bucket

Prints JSON {controller, retrieval, memory, overall, passed}. `passed` is overall
accuracy ≥ threshold. The daily release gate fails the run if this regresses.

Usage:  python scripts/eval_lolm.py [--only controller|retrieval|memory] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def eval_controller() -> float:
    """Production routing accuracy: the MAIN agent searches the web iff a prompt
    needs current facts (currentness/explicit) — the exact predicate shipped in
    research_service.web_route_events. Math/creative/known facts answer directly."""
    from lolm.research.decide import should_search

    def routes_to_web(prompt: str) -> bool:
        d = should_search(prompt)
        sig = d.signals or {}
        return bool(d.search and (sig.get("currentness") or sig.get("explicit_latest")))

    cases = [
        ("what is the top news today", True),
        ("who is the current CEO of OpenAI", True),
        ("latest Llama release notes", True),
        ("the price of bitcoin right now", True),
        ("what are the most recent AI safety incidents", True),
        ("what is 2 + 2", False),
        ("write a haiku about rain", False),
        ("prove that sqrt(2) is irrational", False),
        ("explain how attention works in transformers", False),
        ("summarize the plot of Hamlet", False),
    ]
    ok = sum(1 for prompt, want in cases if routes_to_web(prompt) == want)
    return ok / len(cases)


def eval_memory() -> float:
    """Retrieval staleness: fresh memory is usable, expired memory is flagged stale."""
    from lolm.research.memory import ResearchMemory, ResearchMemoryStore
    with tempfile.TemporaryDirectory() as d:
        store = ResearchMemoryStore(Path(d) / "m.jsonl")
        now = time.time()
        store.write(ResearchMemory(topic="t", claim="fresh fact", summary="s",
                                   source_urls=["https://example.gov/x"],
                                   staleness_policy="30d"))
        sid = store.write(ResearchMemory(topic="t", claim="stale fact", summary="s",
                                         source_urls=["https://example.gov/y"],
                                         staleness_policy="30d"))
        store.mark_stale(sid)   # expire it via the real API
        hits = store.retrieve("fact", now_ts=now, fresh_only=False)
        by_claim = {h.get("claim"): h for h in hits}
        score = 0
        if by_claim.get("fresh fact") and not by_claim["fresh fact"].get("_stale"):
            score += 1
        if by_claim.get("stale fact") and by_claim["stale fact"].get("_stale"):
            score += 1
        return score / 2


def eval_license() -> float:
    """License classifier accuracy on the buckets the training gate depends on."""
    from lolm.research.hf_ingest import classify_license
    cases = [
        ("apache-2.0", "commercial_ok"), ("mit", "commercial_ok"),
        ("cc-by-4.0", "commercial_ok"), ("cc-by-nc-4.0", "noncommercial"),
        ("cc-by-nc-sa-4.0", "noncommercial"), ("gpl-3.0", "copyleft"),
        (None, "unknown"), ("other", "unknown"),
        ("bsd-3-clause", "commercial_ok"), ("some-weird-license", "custom"),
    ]
    ok = sum(1 for lic, want in cases if classify_license(lic) == want)
    return ok / len(cases)


def run(only: str | None = None) -> dict:
    scores = {}
    if only in (None, "controller"):
        scores["controller"] = round(eval_controller(), 4)
    if only in (None, "retrieval", "memory"):
        scores["memory"] = round(eval_memory(), 4)
    if only in (None, "license"):
        scores["license"] = round(eval_license(), 4)
    vals = list(scores.values())
    overall = round(sum(vals) / len(vals), 4) if vals else 0.0
    return {**scores, "overall": overall, "passed": overall >= 0.85,
            "threshold": 0.85, "ran_at": int(time.time())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["controller", "retrieval", "memory", "license"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = run(args.only)
    print(json.dumps(result, indent=None if args.json else 2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
