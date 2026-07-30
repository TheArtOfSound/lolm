#!/usr/bin/env python3
"""Compare two benchmark result files task by task.

    python3 bench/compare.py bench/results/baseline-*.json bench/results/fixed-*.json

Prints per-task movement, the headline deltas, and — because a 12-task run is
stochastic — a blunt note on whether the delta is large enough to mean anything at
the trial count actually used. A change that moves 1 task on repeat=1 is noise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(p):
    d = json.loads(Path(p).read_text())
    s = d["summary"]
    per = {}
    for r in d["results"]:
        per.setdefault(r["id"], []).append(bool(r.get("passed")))
    return s, per, d["results"]


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    a_s, a_p, a_r = load(sys.argv[1])
    b_s, b_p, b_r = load(sys.argv[2])

    print(f"A = {a_s['label']:<12} pass {a_s['passed']}/{a_s['jobs']} = {a_s['pass_rate']:.1%}"
          f"   overclaim {a_s['overclaim_rate']:.1%}   median {a_s['median_wall_s']}s")
    print(f"B = {b_s['label']:<12} pass {b_s['passed']}/{b_s['jobs']} = {b_s['pass_rate']:.1%}"
          f"   overclaim {b_s['overclaim_rate']:.1%}   median {b_s['median_wall_s']}s")
    print()

    fixed, broke, same = [], [], []
    for tid in sorted(set(a_p) | set(b_p)):
        ra, rb = a_p.get(tid, []), b_p.get(tid, [])
        if not ra or not rb:
            print(f"  {tid:<22} (only in one run — skipped)")
            continue
        pa, pb = sum(ra) / len(ra), sum(rb) / len(rb)
        arrow = "→"
        if pb > pa:
            fixed.append(tid); arrow = "↑ FIXED"
        elif pb < pa:
            broke.append(tid); arrow = "↓ REGRESSED"
        else:
            same.append(tid)
        print(f"  {tid:<22} {sum(ra)}/{len(ra)} {arrow} {sum(rb)}/{len(rb)}")

    print()
    print(f"fixed: {len(fixed)}   regressed: {len(broke)}   unchanged: {len(same)}")
    if fixed:
        print("  newly passing: " + ", ".join(fixed))
    if broke:
        print("  NEWLY FAILING: " + ", ".join(broke))

    # Failure reasons on the B side, so the next iteration has somewhere to aim.
    print("\nB-side failures:")
    for r in sorted(b_r, key=lambda x: x["id"]):
        if r.get("passed"):
            continue
        why = (r.get("error") or r.get("hidden_stderr") or "").strip().splitlines()
        tail = why[-1][:110] if why else "(no detail)"
        print(f"  {r['id']:<22} steps={r.get('steps'):<3} {tail}")

    trials = max(len(v) for v in b_p.values()) if b_p else 1
    delta = b_s["pass_rate"] - a_s["pass_rate"]
    print(f"\npass-rate delta {delta:+.1%} at repeat={trials}")
    if trials < 3:
        print("  CAUTION: repeat<3 — a one-or-two-task swing here is inside the noise "
              "band. Re-run with --repeat 3 before treating this as a real gain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
