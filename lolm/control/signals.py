# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Control signals + the fused-uncertainty / sub-pressure math.

Every prompt-time run and every autonomous tick produces a ``ControlSignals``
vector. Values are normalized to 0..1 and their provenance is labelled
(``entropySource`` / ``driftSource``) so a receipt never implies a token-entropy
measurement it did not make.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence

from lolm.control.config import (
    NFET_WEIGHTS, VERIFICATION_WEIGHTS, RETRIEVAL_WEIGHTS, BRANCH_WEIGHTS,
)


def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(x):
        return 0.0
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def sigmoid(x: float) -> float:
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class ControlSignals:
    surfaceUncertainty: float = 0.0
    latentUncertainty: float = 0.0
    entropy: float = 0.0
    entropySource: str = "heuristic_proxy"   # token_logprobs|graft_proxy|heuristic_proxy

    drift: float = 0.0
    driftSource: str = "graft_proxy"          # embedding|lexical_proxy|graft_proxy
    contradictionRisk: float = 0.0

    memoryRelevance: float = 0.0
    memoryPressure: float = 0.0
    retrievalNeed: float = 0.0
    verificationNeed: float = 0.0
    branchNeed: float = 0.0
    toolNeed: float = 0.0

    goalPressure: float = 0.0
    novelty: float = 0.0
    urgency: float = 0.0

    costPressure: float = 0.0
    safetyRisk: float = 0.0
    userInterruptValue: float = 0.0           # V_nudge

    # Auxiliary inputs used by the sub-pressure formulas (kept on the vector so a
    # receipt can reproduce N_ver / N_ret / N_branch).
    claimRisk: float = 0.0
    freshnessRisk: float = 0.0
    userImpact: float = 0.0
    openQuestionImportance: float = 0.0
    lowConfidenceSpanDensity: float = 0.0

    _LOOSE = {
        "uncertainty": "surfaceUncertainty",
        "uTotal": "surfaceUncertainty",
        "contradiction": "contradictionRisk",
        "memrel": "memoryRelevance",
        "nudgeValue": "userInterruptValue",
    }

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "ControlSignals":
        """Build from a dict, accepting both canonical and loose keys, clamped."""
        sig = cls()
        if not d:
            return sig
        fields = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        for k, v in d.items():
            target = k if k in fields else cls._LOOSE.get(k)
            if target is None:
                continue
            if target.endswith("Source"):
                setattr(sig, target, str(v))
            else:
                setattr(sig, target, _clamp01(v))
        return sig

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}


def fused_uncertainty(sig: ControlSignals) -> float:
    """U_total = σ( Σ w_i·signal_i + b ).  Spec section 6."""
    w = NFET_WEIGHTS
    z = (w["surfaceUncertainty"] * sig.surfaceUncertainty
         + w["latentUncertainty"] * sig.latentUncertainty
         + w["entropy"] * sig.entropy
         + w["drift"] * sig.drift
         + w["contradictionRisk"] * sig.contradictionRisk
         + w["verificationNeed"] * sig.verificationNeed
         + w["bias"])
    return sigmoid(z)


def verification_pressure(sig: ControlSignals, u_total: Optional[float] = None) -> float:
    """N_ver — spec section 9."""
    u = fused_uncertainty(sig) if u_total is None else u_total
    w = VERIFICATION_WEIGHTS
    return _clamp01(w["uncertainty"] * u + w["contradiction"] * sig.contradictionRisk
                    + w["claimRisk"] * sig.claimRisk + w["freshnessRisk"] * sig.freshnessRisk
                    + w["userImpact"] * sig.userImpact)


def retrieval_pressure(sig: ControlSignals, u_total: Optional[float] = None) -> float:
    """N_ret — spec section 10."""
    u = fused_uncertainty(sig) if u_total is None else u_total
    w = RETRIEVAL_WEIGHTS
    return _clamp01(w["uncertainty"] * u + w["memoryGap"] * (1.0 - sig.memoryRelevance)
                    + w["openQuestion"] * sig.openQuestionImportance
                    + w["goalPressure"] * sig.goalPressure)


def branch_pressure(sig: ControlSignals, u_total: Optional[float] = None) -> float:
    """N_branch — spec section 11."""
    u = fused_uncertainty(sig) if u_total is None else u_total
    w = BRANCH_WEIGHTS
    return _clamp01(w["drift"] * sig.drift + w["uncertainty"] * u
                    + w["contradiction"] * sig.contradictionRisk
                    + w["lowConfidenceSpanDensity"] * sig.lowConfidenceSpanDensity)


def goal_pressure(goals: Sequence[Dict[str, Any]], now_ms: Optional[float] = None) -> float:
    """P_goal = max_i [ priority·urgency·(1-progress)·staleness ].  Spec section 8."""
    best = 0.0
    for g in goals or []:
        priority = _clamp01(g.get("priority", 0))
        urgency = _clamp01(g.get("urgency", 0))
        progress = _clamp01(g.get("progress", 0))
        stale_after = g.get("staleAfterMs")
        last = g.get("lastTouchedMs")
        if stale_after and last is not None and now_ms is not None:
            staleness = min(1.0, max(0.0, (now_ms - last) / stale_after))
        else:
            staleness = _clamp01(g.get("staleness", 1.0))
        best = max(best, priority * urgency * (1.0 - progress) * staleness)
    return _clamp01(best)


def nudge_value(p_goal: float, expected_user_value: float, confidence: float,
                interruption_cost: float, uncertainty_penalty: float) -> float:
    """V_nudge — spec section 8."""
    return (p_goal * expected_user_value * confidence
            - interruption_cost - uncertainty_penalty)
