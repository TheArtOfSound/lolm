#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Hard-reasoning quality probe — trap questions + multi-step problems with ONE
right answer, run against the live chat to track reasoning quality over time.

Usage:  python3 scripts/hard_reason_probe.py [BASE_URL]   (default $LOLM_BASE or box)
Baseline: 6/6 since the logic-trap reconsider pass (a skeptic second-look on
puzzle-style questions) — including the classic Sally-sisters double-counting
trap. Exits non-zero below 6/6 so a reconsider-pass regression is caught."""
import json, os, re, sys, time, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LOLM_BASE", "http://127.0.0.1:7866")).rstrip("/")

def ask(q, timeout=150):
    body = json.dumps({"command": q, "mode": "chat"}).encode()
    req = urllib.request.Request(BASE + "/api/demo/run/stream", data=body,
                                 headers={"Content-Type": "application/json"})
    ans = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            name = None
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("event: "): name = line[7:]
                elif line.startswith("data: ") and name == "token":
                    try: d = json.loads(line[6:])
                    except Exception: continue
                    if d.get("channel") == "final": ans += d.get("token", "")
    except Exception as exc:
        return f"[ERR {exc}]"
    return ans

def norm(s): return re.sub(r"[,\s]", "", s.lower())

# (label, question, must-contain-any (correct), must-NOT-be-the-headline (trap note))
CASES = [
    # ── original set (tuned against; baseline 6/6) ──
    # bare "5" accepted: a terse brain answers 'Answer with the number of minutes' literally
    ("widgets-5min",  "If it takes 5 machines 5 minutes to make 5 widgets, how long would 100 machines take to make 100 widgets? Answer with the number of minutes.", ["5 minute", "5 min", "five minute", "5minutes", "5"], "100 minute"),
    ("sheep-9",       "A farmer has 17 sheep. All but 9 die. How many sheep are left?", ["9 sheep", "are 9", "is 9", "left: 9", "answer is 9", "9 are", "9."], None),
    ("sally-1sister", "Sally has 3 brothers. Each of her brothers has 2 sisters. How many sisters does Sally have?", ["1 sister", "one sister", "just one", "only one", "has 1"], None),
    ("apples-60",     "A store had 120 apples. They sold one third of them in the morning, then one quarter of the remaining apples in the afternoon. How many apples are left?", ["60"], None),
    ("kg-equal",      "Which weighs more: one kilogram of steel or one kilogram of feathers?", ["same", "equal", "weigh the same", "neither", "both weigh"], None),
    ("number-trick",  "Think of a number. Triple it, add 6, divide the result by 3, then subtract your original number. What is the result?", ["2", "two"], None),
    # ── generalization set: classic traps NEVER tuned against ──
    ("bat-ball-005",  "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost?", ["0.05", "5 cents", "five cents", "$.05"], "0.10"),
    ("lily-47",       "A patch of lily pads doubles in size every day. If it takes 48 days to cover the whole lake, how long would it take to cover half the lake?", ["47"], "24"),
    ("overtake-2nd",  "If you overtake the person in second place in a race, what place are you in?", ["second", "2nd"], "first"),
    ("months-28",     "How many months of the year have 28 days?", ["12", "twelve", "all of them", "every month", "all months"], "1"),
    ("pills-60min",   "A doctor gives you 3 pills and tells you to take one every half hour. How many minutes until you have taken all of them?", ["60", "one hour", "1 hour", "an hour"], "90"),
    # ── false-fire controls: phrased like traps, but the plain answer is right ──
    ("ctrl-sheep-26", "A farmer has 17 sheep and buys 9 more. How many sheep does he have?", ["26"], None),
    ("ctrl-sibs-5",   "Lisa has 3 brothers and 2 sisters. How many siblings does Lisa have?", ["5", "five"], None),
]

REQUIRED = {"widgets-5min", "sheep-9", "sally-1sister", "apples-60", "kg-equal",
            "number-trick", "ctrl-sheep-26", "ctrl-sibs-5"}   # regressions + false-fires gate CI
print("=== hard-reasoning probe ===")
ok = 0
req_fail = []
for label, q, good, trap in CASES:
    a = ask(q)
    na = norm(a)
    hit = any(norm(g) in na for g in good)
    trapped = trap and norm(trap) in na and not hit
    verdict = "PASS" if hit else ("TRAP" if trapped else "FAIL")
    if hit: ok += 1
    elif label in REQUIRED: req_fail.append(label)
    print(f"[{verdict}] {label:16} -> {a.strip()[:95]!r}")
    time.sleep(2)
print(f"\n=== {ok}/{len(CASES)} correct ===")
if req_fail:
    print("REQUIRED failures (regression or reconsider false-fire):", req_fail)
# Exit gates on the tuned set + the false-fire controls; the unseen-trap
# generalization cases are informational (they measure the brain, not LOLM).
sys.exit(1 if req_fail else 0)
