#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Shadow-compare incumbent vs candidate on eligible tasks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.evolution.shadow_compare import shadow_compare


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--limit", type=int, default=32)
    args = ap.parse_args()
    result = shadow_compare(args.root)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
