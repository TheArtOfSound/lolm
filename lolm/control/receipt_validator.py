# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Receipt truth validator — rendered prose may not contradict the trace.

Run this before showing any receipt text. If the structured trace says no action
fired, the prose may not say the agent acted / checked notes / verified /
branched / retrieved. If no baseline was compared, the prose may not claim the
answer beat one. If the receipt claims NFET control, it must actually carry the
NFET fields. A failed validation is shown as a failure, never silently rendered.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Condition name -> phrases forbidden under that condition (lowercased, substring).
FORBIDDEN_WHEN: Dict[str, List[str]] = {
    "no_action": [
        "acted on uncertainty", "acted on its own uncertainty", "checked notes",
        "checked its notes", "verified", "branched", "tried two paths",
        "retrieved", "used a tool", "ran a tool",
    ],
    "no_retrieval": ["checked notes", "retrieved memory", "retrieved", "looked up"],
    "no_branch": ["tried two paths", "branched", "explored alternative"],
    "no_baseline": [
        "beat a baseline", "better than a normal chatbot",
        "better than a plain chatbot", "improved answer quality",
        "no plain chatbot can show you this", "no other chatbot can do this",
    ],
}

REQUIRED_SPANS_NO_ACTION = (
    "Low-confidence spans were detected, but none crossed the action threshold."
)

# The structural fields an NFET-control claim must be backed by.
NFET_REQUIRED_PATHS = ("signals", "decision", "decision.nfet.fieldEnergy",
                       "decision.nfet.thresholds", "decision.nfet.weights")


def _get(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _present(text: str, phrase: str) -> bool:
    return phrase.lower() in (text or "").lower()


def validate_receipt_claims(receipt: Dict[str, Any], rendered_text: str) -> Dict[str, Any]:
    """Validate rendered prose against the receipt's structured trace.

    Returns {"ok": bool, "violations": [...], "missing": [...], "facts": {...}}.
    """
    claim = receipt.get("controllerClaim", {}) or {}
    actions = receipt.get("actions", []) or []
    action_count = int(claim.get("actionCount", 0) or 0)
    spans = receipt.get("lowConfidenceSpans", []) or []
    baseline_compared = bool((receipt.get("answerQuality") or {}).get("baselineCompared"))

    def _did(kinds) -> bool:
        return any((a.get("type") in kinds) and a.get("executed") for a in actions)

    retrieval_used = _did({"retrieve", "recall"})
    branching_used = _did({"branch"})

    violations: List[Dict[str, str]] = []
    missing: List[str] = []

    def _check(condition: str, active: bool) -> None:
        if not active:
            return
        for phrase in FORBIDDEN_WHEN[condition]:
            if _present(rendered_text, phrase):
                violations.append({"rule": condition, "phrase": phrase})

    _check("no_action", action_count == 0)
    _check("no_retrieval", not retrieval_used)
    _check("no_branch", not branching_used)
    _check("no_baseline", not baseline_compared)

    # Required disclosure: spans detected but nothing crossed the bar.
    if spans and action_count == 0 and not _present(rendered_text, REQUIRED_SPANS_NO_ACTION):
        missing.append(REQUIRED_SPANS_NO_ACTION)

    # NFET-control claim must be backed by the NFET fields.
    if claim.get("nfetControlled"):
        for path in NFET_REQUIRED_PATHS:
            if _get(receipt, path) is None:
                missing.append(f"nfet field missing: {path}")

    ok = not violations and not missing
    return {
        "ok": ok,
        "violations": violations,
        "missing": missing,
        "facts": {
            "actionCount": action_count,
            "retrievalUsed": retrieval_used,
            "branchingUsed": branching_used,
            "baselineCompared": baseline_compared,
            "spans": len(spans),
        },
        "message": (
            "" if ok else
            "Receipt validation failed: rendered claim does not match structured trace."
        ),
    }


def safe_receipt_text(receipt: Dict[str, Any], rendered_text: str) -> str:
    """Return the text if it validates, else a safe failure line. Never renders
    a contradicted claim."""
    res = validate_receipt_claims(receipt, rendered_text)
    return rendered_text if res["ok"] else res["message"]
