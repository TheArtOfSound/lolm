#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Longitudinal LEARNING proof — does teaching the AI a fact make it answer a
RELATED (not identical) question it was wrong on before?

This is the un-gameable test: we teach a NOVEL, fictional fact (no model could
know it), then ask a DIFFERENT question that requires REASONING over that fact.
A cold run (fact absent) can't answer; a warm run (fact in memory) retrieves it
and computes the new answer — which was never stored, so it can't be caching.

Run on the box:  python3 scripts/eval_learning.py
Exits non-zero unless COLD is wrong AND WARM is right (real transfer).
"""
import json
import re
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:7866"

# A novel, fictional fact — no model can know it; and the QUESTION is a DIFFERENT
# computation over it, so a correct warm answer proves reasoning-over-memory, not recall.
FACT = "In the fictional Qira flux system, one flux is worth exactly 7 credits."
QUESTION = ("In the Qira flux system, how many credits are 5 flux worth? "
            "Answer with just the number.")
TARGET = "35"          # 5 * 7 — never stored anywhere; must be derived


def ask(q, timeout=150):
    body = json.dumps({"command": q, "mode": "chat"}).encode()
    req = urllib.request.Request(BASE + "/api/demo/run/stream", data=body,
                                 headers={"Content-Type": "application/json"})
    ans = ""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        name = None
        for raw in resp:
            ln = raw.decode("utf-8", "replace").rstrip("\n")
            if ln.startswith("event: "):
                name = ln[7:]
            elif ln.startswith("data: ") and name == "token":
                try:
                    d = json.loads(ln[6:])
                except Exception:
                    continue
                if d.get("channel") == "final":
                    ans += d.get("token", "")
    return ans


def has_target(s):
    return TARGET in re.sub(r"[,\s]", "", s or "")


def main():
    from local_ui.server import MEMORY   # the SAME file-backed store the server reads

    print("=== LEARNING PROOF: teach a fact, then ask a RELATED question ===")
    print(f"FACT taught:  {FACT}")
    print(f"QUESTION:     {QUESTION}  (target {TARGET} = 5x7, never stored)\n")

    cold = ask(QUESTION)
    cold_ok = has_target(cold)
    print(f"[COLD, no memory]  correct={cold_ok}  ->  {cold.strip()[:130]!r}")

    note_id = MEMORY.append_note(FACT, tag="learned-fact", importance=5)
    time.sleep(0.6)
    warm = ask(QUESTION)
    warm_ok = has_target(warm)
    print(f"[WARM, taught it]  correct={warm_ok}  ->  {warm.strip()[:130]!r}")

    # clean up so the eval is repeatable (best-effort)
    try:
        rows = [r for r in MEMORY._read_jsonl(MEMORY.paths.notes) if r.get("id") != note_id]
        MEMORY.paths.notes.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                      encoding="utf-8")
    except Exception:
        pass

    genuine = (not cold_ok) and warm_ok
    print(f"\n=== GENUINE LEARNING (cold wrong, warm right via reasoning-over-memory): {genuine} ===")
    if not genuine and cold_ok:
        print("NOTE: the base model already knew/guessed it — pick a more novel fact.")
    sys.exit(0 if genuine else 1)


if __name__ == "__main__":
    main()
