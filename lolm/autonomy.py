# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Uncertainty-gated autonomy — when may the agent act on its own?

This is the layer Hellhound's runtime is missing and LOLM's math makes sound.
NFET's control policy decides micro-actions *during* generation (retrieve /
verify / branch / finalize). This decides the bigger question *after* an answer
or before a real-world action: given the run's measured uncertainty and the
RISK of the action, do we

    ACT      — execute autonomously,
    GATHER   — get more evidence / verify first (which re-measures U lower), or
    ESCALATE — hand to a human,

and we decide it with a calibrated probability, not a feeling.

The rule (decision-theoretic, auditable):

    p   = calibrated P(correct | measured_uncertainty)        # lolm.calibration
    bar = 1 - allowed_error(risk_tier)                         # below
    ACT      if p >= bar
    GATHER   if p >= bar - GATHER_MARGIN and tier is recoverable
    ESCALATE otherwise

Risk tiers set the allowed error, NOT confidence vibes:

    read         15%   read-only / no side effect
    reversible    5%   reversible writes (draft, local file, scratch)
    external      2%   outward-facing (post, message, non-destructive API)
    irreversible 0.5%  money, deletion, sending, anything you cannot take back

An irreversible action is never downgraded to GATHER — if it is not already
clearly safe, a human decides. That asymmetry is the safety property: the agent
is bold where mistakes are cheap and humble where they are not, and the bar is a
number you can point to in the receipt.

Pure Python; pairs with lolm.calibration. No model import — runs in the receipt
path. ``risk_profile`` strings line up with lolm.critique.risk_profile so the
two compose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lolm.calibration import UncertaintyCalibrator, _default_p_correct

# Allowed error rate per tier. The agent acts autonomously only when its
# calibrated P(correct) is at least (1 - allowed_error).
RISK_TIERS: Dict[str, float] = {
    "read": 0.15,
    "reversible": 0.05,
    "external": 0.02,
    "irreversible": 0.005,
}
TIER_ORDER = ("read", "reversible", "external", "irreversible")

# How far below the bar we will still try to GATHER evidence (which lowers U on
# re-measurement) before escalating — only for recoverable tiers.
GATHER_MARGIN = 0.15

# A high-stakes prompt class (from critique.risk_profile) lifts the action's
# floor tier: a "financial" or "irreversible" answer is treated as irreversible
# even if the mechanical action looks reversible, because acting on a wrong
# money/legal/medical answer is the costly mistake.
PROFILE_FLOOR: Dict[str, str] = {
    "financial": "irreversible",
    "legal": "irreversible",
    "medical": "irreversible",
    "safety": "irreversible",
    "quantitative": "external",
    "formal_logic": "external",
    "factual": "external",
}

ACT, GATHER, ESCALATE = "act", "gather", "escalate"

# Actions that ALWAYS require a human, regardless of how well-calibrated and
# confident the agent is. Autonomy is for everything recoverable; these get the
# agent's calibrated confidence + a verified outcome PREVIEW, then one human
# decision. The agent provably cannot move money, send on your behalf, delete,
# or deploy on its own — that ceiling is in the math, not a policy doc. Pass
# ``require_human=frozenset()`` to opt out per call.
HARD_HUMAN_GATE = frozenset({
    "payment", "transfer", "trade", "send", "email", "delete", "deploy",
})


@dataclass
class AutonomyDecision:
    mode: str                     # act | gather | escalate
    tier: str
    p_correct: float
    bar: float                    # 1 - allowed_error(tier)
    margin: float                 # p_correct - bar (negative => below bar)
    uncertainty: float
    calibrated: bool              # False => prior, treat with extra caution
    reason: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "tier": self.tier,
            "p_correct": round(self.p_correct, 4),
            "bar": round(self.bar, 4),
            "margin": round(self.margin, 4),
            "uncertainty": round(self.uncertainty, 4),
            "calibrated": self.calibrated,
            "reason": self.reason,
        }


def _max_tier(a: str, b: str) -> str:
    return a if TIER_ORDER.index(a) >= TIER_ORDER.index(b) else b


def classify_action_risk(action_kind: str, risk_profiles: Optional[List[str]] = None,
                         base_tier: Optional[str] = None) -> str:
    """Resolve the effective risk tier for an action.

    ``action_kind`` is the mechanical reversibility (e.g. "read", "draft",
    "post", "payment", "delete", "send"). ``risk_profiles`` is the prompt's risk
    classification from critique. The effective tier is the MORE cautious of the
    mechanical tier and any profile floor — you cannot make a money answer safe
    by routing it through a "reversible" button.
    """
    mech = base_tier or _ACTION_TIER.get((action_kind or "").lower(), "external")
    tier = mech
    for p in (risk_profiles or []):
        floor = PROFILE_FLOOR.get((p or "").lower())
        if floor:
            tier = _max_tier(tier, floor)
    return tier


_ACTION_TIER: Dict[str, str] = {
    "answer": "read", "advise": "read", "deliver": "read",
    "read": "read", "search": "read", "retrieve": "read", "lookup": "read",
    "draft": "reversible", "write_file": "reversible", "scratch": "reversible",
    "edit": "reversible", "branch": "reversible", "run_code": "reversible",
    "post": "external", "comment": "external", "api_call": "external",
    "publish": "external", "schedule": "external",
    "send": "irreversible", "email": "irreversible", "payment": "irreversible",
    "transfer": "irreversible", "delete": "irreversible", "deploy": "irreversible",
    "trade": "irreversible",
}


class AutonomyGate:
    """Decides act / gather / escalate from calibrated uncertainty + risk."""

    def __init__(self, calibrator: Optional[UncertaintyCalibrator] = None,
                 gather_margin: float = GATHER_MARGIN):
        self.calibrator = calibrator
        self.gather_margin = gather_margin

    def p_correct(self, uncertainty: float) -> tuple:
        if self.calibrator is not None and self.calibrator.is_fit:
            return self.calibrator.p_correct(uncertainty), True
        return _default_p_correct(uncertainty), False

    def decide(self, uncertainty: float, tier: str,
               no_telemetry: bool = False) -> AutonomyDecision:
        """The gate. ``no_telemetry=True`` forces escalation on any non-read tier
        — a missing uncertainty signal is not permission, it is a blind spot."""
        tier = tier if tier in RISK_TIERS else "external"
        allowed = RISK_TIERS[tier]
        bar = 1.0 - allowed
        p, calibrated = self.p_correct(uncertainty)
        margin = p - bar

        if no_telemetry and tier != "read":
            return AutonomyDecision(
                ESCALATE, tier, p, bar, margin, uncertainty, calibrated,
                "no uncertainty signal was measured — a blind spot is not "
                "consent to act on a "
                f"{tier} action",
            )
        if margin >= 0:
            note = "" if calibrated else " (uncalibrated prior — verify early)"
            return AutonomyDecision(
                ACT, tier, p, bar, margin, uncertainty, calibrated,
                f"calibrated P(correct)={p:.3f} ≥ bar {bar:.3f} for a {tier} "
                f"action{note}",
            )
        recoverable = tier in ("read", "reversible", "external")
        if recoverable and margin >= -self.gather_margin:
            return AutonomyDecision(
                GATHER, tier, p, bar, margin, uncertainty, calibrated,
                f"P(correct)={p:.3f} is {(-margin):.3f} below the {tier} bar "
                f"{bar:.3f} — gather evidence / verify, then re-measure",
            )
        return AutonomyDecision(
            ESCALATE, tier, p, bar, margin, uncertainty, calibrated,
            f"P(correct)={p:.3f} is below the {tier} bar {bar:.3f}"
            + ("" if recoverable else " and the action is irreversible")
            + " — hand to a human",
        )

    def gate_action(self, uncertainty: float, action_kind: str,
                    risk_profiles: Optional[List[str]] = None,
                    no_telemetry: bool = False,
                    require_human: Optional[frozenset] = None) -> AutonomyDecision:
        """Classify the action's risk, honour the hard human-gate, then decide."""
        tier = classify_action_risk(action_kind, risk_profiles)
        gate = HARD_HUMAN_GATE if require_human is None else require_human
        if (action_kind or "").lower() in gate:
            p, calibrated = self.p_correct(uncertainty)
            bar = 1.0 - RISK_TIERS[tier]
            return AutonomyDecision(
                ESCALATE, tier, p, bar, p - bar, uncertainty, calibrated,
                f"'{action_kind}' is hard-gated to a human regardless of "
                f"confidence (calibrated P(correct)={p:.3f}) — the agent "
                "prepares it and previews the outcome; you approve it",
            )
        return self.decide(uncertainty, tier, no_telemetry=no_telemetry)
