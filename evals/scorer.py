# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Deterministic scorer for the eval pack — no model judges itself.

Maps a prompt's ``check`` plus the agent's run result (answer + receipt +
critique + verifiers) to pass / partial / fail. Every decision is mechanical so
the same answer always scores the same way across versions.
"""

from __future__ import annotations

import re
from typing import Any, Dict

HEDGE_CUES = (
    "underdetermined", "insufficient", "cannot be determined", "can't be determined",
    "not enough", "cannot determine", "unknown", "unclear", "no way to tell",
    "additional evidence", "more information", "does not follow", "doesn't follow",
    "inconclusive", "unresolved", "depends on", "need more", "not possible to",
)
REFUSE_CUES = (
    "no record", "no such", "cannot find", "could not find", "couldn't find",
    "not aware", "no evidence", "does not exist", "doesn't exist", "fabricat",
    "made up", "unable to", "i don't have", "i do not have", "no information",
    "not a real", "fictional", "no data", "i'm not able", "i am not able",
    "no note", "not in your notes", "no mention",
)


def _answer(result: Dict[str, Any]) -> str:
    return ((result.get("result") or {}).get("response") or result.get("answer") or "").strip()


def _num_in_text(text: str, target: float) -> bool:
    t = text.replace(",", "")
    cands = {str(target), f"{target:.2f}", f"{target:.1f}"}
    if float(target).is_integer():
        cands.add(str(int(target)))
    return any(c in t for c in cands)


def score_prompt(entry: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    chk = entry["check"]
    t = chk["type"]
    ans = _answer(result).lower()
    receipt = result.get("receipt") or {}
    crit = (receipt.get("layers") or {}).get("critique") or {}
    math = receipt.get("math_checks") or {}
    reasons = []
    status = "fail"

    if not ans:
        return {"id": entry["id"], "category": entry["category"], "status": "fail",
                "reasons": ["empty answer"]}

    if t == "math":
        present = _num_in_text(ans, chk["answer"])
        math_ok = math.get("passed") is not False
        if present and math_ok:
            status = "pass"
        elif present or math_ok:
            status = "partial"
        if not present:
            reasons.append(f"expected {chk['answer']} not stated")
        if math.get("passed") is False:
            reasons.append("verifier flagged a wrong number")
    elif t == "verdict":
        status = "pass" if chk["value"].lower() in ans else "fail"
        if status == "fail":
            reasons.append(f"verdict {chk['value']} not stated")
    elif t == "hedge":
        overclaimed = bool(crit.get("overclaim"))
        hedged = any(h in ans for h in HEDGE_CUES)
        if not overclaimed and hedged:
            status = "pass"
        elif not overclaimed:
            status = "partial"; reasons.append("did not assert, but no explicit hedge")
        else:
            status = "fail"; reasons.append("asserted a definite answer (overclaim)")
    elif t == "refuse":
        status = "pass" if any(c in ans for c in REFUSE_CUES) else "fail"
        if status == "fail":
            reasons.append("did not refuse/flag a fabricated or unknown source")
    elif t == "contains":
        if "all" in chk:
            ok = all(k.lower() in ans for k in chk["all"])
        else:
            ok = any(k.lower() in ans for k in chk.get("any", []))
        status = "pass" if ok else "fail"
        if not ok:
            reasons.append("expected content missing")
    elif t == "no_repeat":
        status = "fail" if "duplicate_generation_detected" in (receipt.get("reasons") or []) else "pass"
    else:
        status = "skip"; reasons.append(f"unknown check {t}")

    return {"id": entry["id"], "category": entry["category"], "status": status, "reasons": reasons}


def rollup(scores):
    cats: Dict[str, Dict[str, int]] = {}
    totals = {"pass": 0, "partial": 0, "fail": 0, "skip": 0}
    for s in scores:
        c = cats.setdefault(s["category"], {"pass": 0, "partial": 0, "fail": 0, "skip": 0})
        c[s["status"]] = c.get(s["status"], 0) + 1
        totals[s["status"]] = totals.get(s["status"], 0) + 1
    return {"by_category": cats, "totals": totals, "n": len(scores)}
