#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Run one live web-research job (keyless search → read → source-backed memory).

Usage:  python scripts/qira_web_research.py ["a topic or question"]
Writes source-backed memory to runs/research_memory.jsonl and prints the receipt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ui import internet_tools
from lolm.research.memory import ResearchMemoryStore
from lolm.research.jobs import ResearchJob, run_job, default_jobs


def main() -> int:
    store = ResearchMemoryStore(ROOT / "runs" / "research_memory.jsonl")
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])
        job = ResearchJob(job_id="adhoc", topic=topic, queries=[topic], schedule="manual")
    else:
        job = default_jobs()[0]
    rcpt = run_job(job, search_fn=internet_tools.web_search,
                   fetch_fn=internet_tools.fetch_url, memory_store=store)
    print(json.dumps(rcpt, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
