#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Build datasets and train a candidate LOLM-Core adapter."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.evolution.controller_builder import build_controller_from_repo
from lolm.evolution.preference_builder import build_preference_from_files
from lolm.evolution.sft_builder import build_sft_from_gold_file
from lolm.evolution.train_candidate import train_candidate
from lolm.evolution.verifier_builder import build_verifier_from_repo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--dry-run", action="store_true", help="Stub adapter (no MLX)")
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--skip-datasets", action="store_true")
    args = ap.parse_args()

    out = {}
    if not args.skip_datasets:
        out["sft"] = build_sft_from_gold_file(args.root)
        out["preference"] = build_preference_from_files(args.root)
        out["controller"] = build_controller_from_repo(args.root)
        out["verifier"] = build_verifier_from_repo(args.root)
    out["train"] = train_candidate(
        args.root, dry_run=args.dry_run, iters=args.iters,
    )
    # drop huge nested manifest echo for CLI
    if "manifest" in out["train"]:
        out["train"] = {k: v for k, v in out["train"].items() if k != "manifest"}
        out["train"]["manifest_path"] = out["train"].get("manifest_path")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
