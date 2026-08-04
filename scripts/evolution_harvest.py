#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Harvest product receipts → Bronze → Silver → Gold."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.evolution.gold_filter import build_gold_pipeline
from lolm.evolution.harvest import harvest_repo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--max-per-source", type=int, default=5000)
    args = ap.parse_args()
    h = harvest_repo(args.root, max_per_source=args.max_per_source)
    g = build_gold_pipeline(args.root, bronze_path=Path(h["bronze_path"]))
    print(json.dumps({"harvest": h, "gold": g}, indent=2))


if __name__ == "__main__":
    main()
