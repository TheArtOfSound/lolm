#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Train the coding NFET control head and write runs/nfet_controller/code_head.pt

    PYTHONPATH=. python scripts/train_code_nfet.py
    PYTHONPATH=. python scripts/train_code_nfet.py \\
        --receipts runs/code_receipts.jsonl \\
        --receipts /opt/apps/lolm/runs/code_receipts.jsonl \\
        --out runs/nfet_controller/code_head.pt
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lolm.code_nfet_train import train_coding_head


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--synthetic", type=int, default=1200)
    ap.add_argument("--distill", type=int, default=600)
    ap.add_argument("--receipts", action="append", default=[],
                    help="code_receipts.jsonl path (repeatable)")
    ap.add_argument("--out", default="runs/nfet_controller/code_head.pt")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    receipts = [Path(p) for p in args.receipts]
    # Sensible defaults if none given.
    if not receipts:
        for cand in (
            root / "runs" / "code_receipts.jsonl",
            root / "local_ui" / "data" / "improvement_log.jsonl",
        ):
            if cand.exists():
                receipts.append(cand)

    result = train_coding_head(
        Path(args.out),
        synthetic=args.synthetic,
        distill=args.distill,
        receipt_paths=receipts,
        epochs=args.epochs,
        seed=args.seed,
    )
    print(f"[code-nfet] wrote {result.path}")
    print(f"[code-nfet] rows={result.n_rows} train_acc={result.train_acc:.3f} "
          f"val_acc={result.val_acc:.3f} counts={result.class_counts}")


if __name__ == "__main__":
    main()
