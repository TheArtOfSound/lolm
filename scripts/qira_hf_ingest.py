#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Run one Hugging Face daily ingest and print the receipt (Layer 1-2, no weights)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.research.memory import ResearchMemoryStore
from lolm.research import hf_ingest as hi


def main() -> int:
    runs = ROOT / "runs"
    store = ResearchMemoryStore(runs / "hf_memory.jsonl")
    queue = hi.TrainingCandidateQueue(runs / "hf_candidates.jsonl")
    topics = sys.argv[1:] or hi.HF_TOPICS[:6]
    res = hi.ingest(memory_store=store, queue=queue, topics=topics, per_topic=8)
    with (runs / "hf_ingest_receipts.jsonl").open("a") as f:
        f.write(json.dumps(res.receipt) + "\n")
    (runs / "hf_ingest_latest.json").write_text(json.dumps(res.receipt, indent=2))
    print(json.dumps(res.receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
