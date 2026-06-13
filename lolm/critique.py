# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Deterministic post-run critique — grades the ANSWER, separately from control.

Two CRITICAL complaints this module answers directly:

  #2 "The controller is not aggressive enough on hard reasoning." A system whose
     promise is uncertainty-aware action must ACT more often on the prompts that
     deserve it — money, math, dates, formal logic, contradictions — not finish
     confidently and look like a fancy chatbot. ``risk_profile`` + ``should_audit``
     classify a prompt so the agent can force a verify pass on exactly those.

  #3 "The answer quality is still often generic / wrong even after a control
     action." Control visibility is not answer quality. ``assess`` grades the
     final answer on deterministic, defensible axes — math correctness (from the
     verifiers), contract adherence, and the specific failure the battery caught:
     asserting a definite answer to an explicitly UNDERDETERMINED question (T4
     named a culprit when the right answer was "insufficient evidence").

Pure Python, no model. It never rewards telemetry; it reads the text and the
contract and reports what it can actually check — including, loudly, when it
cannot tell (so a thin answer never passes by silence).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ── prompt risk classification (drives controller aggression, complaint #2) ───

_RISK_CUES: Dict[str, tuple] = {
    # money / budgets / rates — wrong arithmetic here erases trust fastest
    "financial": ("$", "cost", "budget", "price", "salary", "revenue", "profit",
                  "invoice", "per hour", "/hour", "/hr", "wage", "expense", "dollars"),
    # general quantitative reasoning
    "quantitative": ("calculate", "how much", "how many", "total", "sum",
                     "percent", "%", "average", "multiply", "divide"),
    # dates / durations / scheduling
    "temporal": ("deadline", "weeks", "days", "months", "schedule", "by when",
                 "how long", "duration", "timeline"),
    # formal logic / proof / verification
    "logical": ("prove", "proof", "satisfiable", "unsatisfiable", "valid",
                "contradiction", "theorem", "if and only if", "entails",
                "first invalid step", "counterexample"),
    # explicitly underdetermined — the answer must REFUSE to guess
    "underdetermined": ("do not guess", "don't guess", "underdetermined",
                        "insufficient", "what additional evidence", "do not name",
                        "cannot be determined", "if it follows", "what does not follow"),
}

# Phrases that show an answer is HEDGING appropriately (not overclaiming).
_HEDGE_CUES = (
    "underdetermined", "insufficient", "cannot be determined", "can't be determined",
    "not enough", "cannot determine", "can't determine", "unknown", "unclear",
    "no way to tell", "either", "any of", "additional evidence", "more information",
    "does not follow", "doesn't follow", "not possible to", "inconclusive",
)


def _quant_present(text: str) -> bool:
    # a digit adjacent to an operator or money symbol => real quantitative content
    return bool(re.search(r"\d\s*[-+x*×·/%]|\$\s*\d|\d\s*(?:percent|hours|weeks|days)\b",
                          text, re.IGNORECASE))


def risk_profile(command: str) -> List[str]:
    """Tags describing why a prompt deserves extra scrutiny. Empty = low-stakes."""
    lc = (command or "").lower()
    tags = [name for name, cues in _RISK_CUES.items() if any(c in lc for c in cues)]
    if "quantitative" not in tags and _quant_present(command or ""):
        tags.append("quantitative")
    return tags


def should_audit(command: str) -> bool:
    """True when the controller should be FORCED to verify rather than allowed to
    finish confidently — the heart of complaint #2."""
    tags = set(risk_profile(command))
    return bool(tags & {"financial", "quantitative", "logical", "underdetermined", "temporal"})


# ── answer grading (complaint #3) ─────────────────────────────────────────────

def _asserts_definite_culprit(answer: str) -> bool:
    """Heuristic: does the answer commit to a single definite actor/answer?
    e.g. 'Morgan entered the vault', 'the answer is X', 'X did it'."""
    a = answer.strip()
    if not a:
        return False
    patterns = (
        r"\bthe answer is\b", r"\bit was\b\s+\w+", r"\b\w+ (?:did it|is the culprit|opened|entered)\b",
        r"\bthe culprit is\b", r"\bmust be\b\s+\w+", r"\btherefore\s+\w+\s+(?:did|is|entered|opened)\b",
    )
    return any(re.search(p, a, re.IGNORECASE) for p in patterns)


def assess(command: str, answer: str, *,
           contract: Optional[Dict[str, Any]] = None,
           verifiers: Optional[Dict[str, Any]] = None,
           control_acted: bool = False) -> Dict[str, Any]:
    """Grade an answer deterministically. Returns labels + a plain read.

    {
      "labels": [...],            # machine failure labels
      "risk_profile": [...],      # why this prompt was high-stakes (if any)
      "math": "passed|failed|none",
      "contract": "passed|failed|none",
      "overclaim": bool,          # asserted a definite answer to an underdetermined prompt
      "audit_expected": bool,     # should_audit(command)
      "audit_satisfied": bool,    # control actually acted on a high-stakes prompt
      "verdict": "...", "plain": "...",
    }
    """
    answer = (answer or "").strip()
    labels: List[str] = []
    profile = risk_profile(command)
    audit_expected = should_audit(command)

    # math (from the deterministic verifiers)
    vp = (verifiers or {}).get("passed")
    math = "failed" if vp is False else "passed" if vp is True else "none"
    if vp is False:
        labels.append("math_check_failed")

    # contract adherence (from check_contract)
    cp = (contract or {}).get("passed")
    contract_state = "failed" if cp is False else "passed" if cp is True else "none"
    if cp is False:
        labels.append("task_contract_failed")

    # the T4 failure: a definite answer to an explicitly underdetermined question
    lc = (command or "").lower()
    underdetermined_prompt = any(c in lc for c in _RISK_CUES["underdetermined"])
    hedged = any(h in answer.lower() for h in _HEDGE_CUES)
    overclaim = bool(underdetermined_prompt and answer and not hedged
                     and _asserts_definite_culprit(answer))
    if overclaim:
        labels.append("overclaim_on_underdetermined")

    # a high-stakes prompt that the controller never acted on (and the math/contract
    # were not independently confirmed) is exactly the "fancy chatbot" risk #2 names
    audit_satisfied = bool(control_acted or vp is True)
    if audit_expected and not audit_satisfied:
        labels.append("high_stakes_unverified")

    if "math_check_failed" in labels:
        verdict, plain = "answer_math_failed", "A number in the answer is wrong — re-derived and contradicted."
    elif overclaim:
        verdict, plain = "answer_overclaimed", ("The prompt was underdetermined but the answer named a "
                                                "definite culprit instead of saying the evidence is insufficient.")
    elif "task_contract_failed" in labels:
        verdict, plain = "answer_off_contract", "The answer missed an explicit requirement of the prompt."
    elif "high_stakes_unverified" in labels:
        verdict, plain = "answer_unverified_high_stakes", ("A money/logic/date prompt was answered without a "
                                                           "verification pass or a passing math check.")
    else:
        verdict, plain = "answer_no_deterministic_fault", "No deterministic fault found (this is not proof the answer is good)."

    return {
        "labels": labels,
        "risk_profile": profile,
        "math": math,
        "contract": contract_state,
        "overclaim": overclaim,
        "audit_expected": audit_expected,
        "audit_satisfied": audit_satisfied,
        "verdict": verdict,
        "plain": plain,
    }
