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


def ask(q, timeout=150, session_id=None):
    payload = {"command": q, "mode": "chat"}
    if session_id:
        payload["session_id"] = session_id
    body = json.dumps(payload).encode()
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


def _num_in(s, target):
    return target in re.sub(r"[,\s]", "", s or "")


def end_to_end():
    """The full loop with NO manual memory write: TEACH via the chat API (an
    explicit 'Remember:' marker → auto-captured), then ASK a RELATED question via
    the API in a separate call. Proves capture + retrieve + use end to end."""
    from local_ui.server import MEMORY
    fact = "Remember: in the fictional Zorb arena, one zorb is worth exactly 4 points."
    q = "In the Zorb arena, how many points are 6 zorb worth? Answer with just the number."
    target = "24"   # 6 * 4 — never stored
    print("\n=== END-TO-END (capture via chat API — nothing written by hand) ===")
    cold = ask(q)
    cold_ok = _num_in(cold, target)
    print(f"[COLD]         correct={cold_ok}  ->  {cold.strip()[:105]!r}")
    ack = ask(fact)   # teach it through the real API; auto-capture stores the fact
    print(f"[TAUGHT (API)] reply: {ack.strip()[:75]!r}")
    time.sleep(0.6)
    warm = ask(q)
    warm_ok = _num_in(warm, target)
    print(f"[WARM]         correct={warm_ok}  ->  {warm.strip()[:105]!r}")
    try:   # cleanup so it's repeatable
        rows = [r for r in MEMORY._read_jsonl(MEMORY.paths.notes)
                if "zorb" not in (r.get("text", "").lower())]
        MEMORY.paths.notes.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                      encoding="utf-8")
    except Exception:
        pass
    ok = (not cold_ok) and warm_ok
    print(f"=== CAPTURE→RETRIEVE→USE end-to-end (cold wrong, warm right): {ok} ===")
    return ok


def isolation():
    """Session-scoped capture: a fact one visitor states is learned FOR THEM (this
    chat) and used later, but a DIFFERENT session can't see it — no cross-visitor
    poisoning of the shared store."""
    from local_ui.server import MEMORY
    A, B = "evalSessionA1", "evalSessionB2"
    fact = "In the Blorp league, one blorp is worth exactly 9 points."
    q = "In the Blorp league, how many points are 3 blorps worth? Answer with just the number."
    target = "27"   # 3 * 9, novel and unguessable
    print("\n=== SESSION ISOLATION (auto-capture scoped to a chat) ===")
    ask(fact, session_id=A)                      # session A states the fact -> learned for A
    time.sleep(0.6)
    warm_a = ask(q, session_id=A)
    cold_b = ask(q, session_id=B)
    a_ok = _num_in(warm_a, target)
    b_leak = _num_in(cold_b, target)
    print(f"[A taught it, A asks]  uses it={a_ok}  ->  {warm_a.strip()[:95]!r}")
    print(f"[B never taught, asks] LEAKED={b_leak}  ->  {cold_b.strip()[:95]!r}")
    try:
        rows = [r for r in MEMORY._read_jsonl(MEMORY.paths.notes)
                if "blorp" not in (r.get("text", "").lower())]
        MEMORY.paths.notes.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                      encoding="utf-8")
    except Exception:
        pass
    ok = a_ok and not b_leak
    print(f"=== ISOLATION (A uses it, B can't see it): {ok} ===")
    return ok


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
    return genuine


if __name__ == "__main__":
    inject_ok = main()          # direct-inject half (retrieval + finalizer)
    capture_ok = end_to_end()   # full loop via the API (capture too)
    iso_ok = isolation()        # per-session scoping (safe on the shared demo)
    sys.exit(0 if (inject_ok and capture_ok and iso_ok) else 1)
