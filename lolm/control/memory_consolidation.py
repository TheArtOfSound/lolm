# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Memory consolidation — decide whether a candidate memory deserves storage.

Between prompts (or after an answer) LOLM reviews memory candidates and writes
only those whose score clears a threshold, with an explicit retention class and a
receipt of the decision. A memory write is a controller action with a number
behind it, not a side effect.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from lolm.control.config import MEMORY_WRITE_WEIGHTS, MEMORY_THRESHOLDS


def memory_write_score(c: Dict[str, Any]) -> float:
    """MemoryWriteScore — spec section 15. Inputs are 0..1 features of the candidate."""
    w = MEMORY_WRITE_WEIGHTS
    return (w["goal"] * float(c.get("goalRelevance", 0))
            + w["future"] * float(c.get("futureUsefulness", 0))
            + w["user"] * float(c.get("userPreferenceImportance", 0))
            + w["fact"] * float(c.get("factualStability", 0))
            + w["novelty"] * float(c.get("novelty", 0))
            - w["privacy"] * float(c.get("privacyRisk", 0))
            - w["duplicate"] * float(c.get("duplicationPenalty", 0)))


def retention_class(score: float, privacy_risk: float = 0.0) -> str:
    if privacy_risk >= 0.8:
        return "do_not_store"
    if score >= MEMORY_THRESHOLDS["longTerm"]:
        return "long_term"
    if score >= MEMORY_THRESHOLDS["project"]:
        return "project"
    if score >= MEMORY_THRESHOLDS["write"]:
        return "session"
    return "ephemeral"


def decide_memory_write(candidate: Dict[str, Any],
                        scope: str = "shared_demo") -> Dict[str, Any]:
    """Score a candidate, decide write/skip, and return a memory-write receipt row."""
    score = memory_write_score(candidate)
    privacy = float(candidate.get("privacyRisk", 0))
    rclass = retention_class(score, privacy)
    written = score > MEMORY_THRESHOLDS["write"] and rclass != "do_not_store"
    reason = ("score above write threshold" if written else
              "privacy risk too high — not stored" if rclass == "do_not_store" else
              "score below write threshold")
    return {
        "text": candidate.get("text", "")[:400],
        "score": round(score, 4),
        "threshold": MEMORY_THRESHOLDS["write"],
        "written": written,
        "scope": scope,
        "retentionClass": rclass,
        "privacyRisk": round(privacy, 4),
        "duplicationPenalty": round(float(candidate.get("duplicationPenalty", 0)), 4),
        "reason": reason,
    }
