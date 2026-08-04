#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Evolution daemon — cycle when data thresholds are met (not every message).

  PYTHONPATH=. python scripts/evolution_daemon.py --once --dry-run --force
  PYTHONPATH=. python scripts/evolution_daemon.py --interval 3600 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.evolution.cycle import run_evolution_cycle, thresholds_met


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--once", action="store_true", help="Single cycle then exit")
    ap.add_argument("--interval", type=int, default=3600, help="Seconds between checks")
    ap.add_argument("--dry-run", action="store_true",
                    help="Force dry-run stub adapters (no MLX train)")
    ap.add_argument("--real-train", action="store_true",
                    help="Force real LoRA (requires mlx-lm)")
    ap.add_argument("--force", action="store_true", help="Ignore data thresholds")
    ap.add_argument("--canary", type=float, default=0.05)
    ap.add_argument("--no-shadow-required", action="store_true")
    args = ap.parse_args()
    # Auto: real train when mlx available unless --dry-run
    dry: bool | None
    if args.dry_run:
        dry = True
    elif args.real_train:
        dry = False
    else:
        dry = None  # cycle auto-detects mlx

    def one() -> dict:
        return run_evolution_cycle(
            args.root,
            dry_run=dry,
            force=args.force,
            canary_pct=args.canary,
            require_shadow=not args.no_shadow_required,
        )

    if args.once:
        report = one()
        print(json.dumps(report, indent=2, default=str))
        return

    print(f"[evolution] daemon interval={args.interval}s dry_run={dry}", flush=True)
    while True:
        thr = thresholds_met(args.root, force=args.force)
        print(json.dumps({"threshold": thr}, default=str), flush=True)
        if thr["met"] or args.force:
            report = one()
            print(json.dumps({"decision": report.get("decision"), "seconds": report.get("seconds")},
                             default=str), flush=True)
        else:
            print("[evolution] waiting for more Gold data", flush=True)
        if args.once:
            break
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
