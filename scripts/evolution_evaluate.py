#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Evaluate a candidate adapter against the four promotion gates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.evolution.evaluate_candidate import evaluate_candidate
from lolm.evolution.schema import default_paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--candidate", type=Path, required=True, help="Candidate adapter directory")
    ap.add_argument("--require-shadow", action="store_true")
    ap.add_argument("--shadow-json", type=Path, default=None)
    args = ap.parse_args()

    shadow = None
    if args.shadow_json and args.shadow_json.exists():
        shadow = json.loads(args.shadow_json.read_text())
    else:
        latest = default_paths(args.root).receipts / "shadow_latest.json"
        if latest.exists():
            shadow = json.loads(latest.read_text())

    result = evaluate_candidate(
        args.root,
        args.candidate,
        require_shadow=args.require_shadow,
        shadow_result=shadow,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
