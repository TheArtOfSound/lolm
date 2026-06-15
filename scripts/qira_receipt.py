#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Print the most recent daily release receipt (markdown), or JSON with --json."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "runs" / "daily"


def main() -> int:
    want_json = "--json" in sys.argv
    ext = "json" if want_json else "md"
    files = sorted(DAILY.glob(f"*.{ext}"))
    if not files:
        print(f"no daily receipts yet in {DAILY} — run `npm run agent:daily-learned-update`")
        return 1
    print(files[-1].read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
