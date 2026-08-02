# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Decomposed confidence metrics.

Never display a bare p= value as artifact correctness.
Every probability must identify its target event and calibration set.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ConfidenceBundle:
    """Typed confidence dimensions — never combined into a bare 'confidence'."""

    policy_action_certainty: float = 0.0
    """P(preferred control action is verify/branch/retrieve/finalize)."""

    artifact_correctness_estimate: float = 0.0
    """Estimated P(artifact satisfies functional contract)."""

    verification_coverage: float = 0.0
    """Fraction of required criteria actually tested."""

    contract_completion: float = 0.0
    """Fraction of hard criteria satisfied."""

    capability_feasibility: float = 1.0
    """Whether the environment can run the required verifier (0/1 or soft)."""

    calibration_status: str = "uncalibrated"  # uncalibrated | provisional | calibrated
    policy_action_label: str = ""
    target_events: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target_events:
            self.target_events = {
                "policy_action_certainty": "control_action_label",
                "artifact_correctness_estimate": "contract_satisfied",
                "verification_coverage": "criteria_tested",
                "contract_completion": "hard_clauses_green",
                "capability_feasibility": "verifier_available",
            }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def ui_fields(self) -> Dict[str, Any]:
        """User-facing fields — never a bare field named only 'confidence'."""
        return {
            "policy_action_certainty": round(self.policy_action_certainty, 4),
            "policy_action_label": self.policy_action_label,
            "artifact_correctness_estimate": round(self.artifact_correctness_estimate, 4),
            "verification_coverage": round(self.verification_coverage, 4),
            "contract_completion": round(self.contract_completion, 4),
            "capability_feasibility": round(self.capability_feasibility, 4),
            "calibration_status": self.calibration_status,
            "target_events": dict(self.target_events),
        }


def action_certainty_label(action: str, p: float) -> str:
    """Explicit wording: action certainty, not artifact confidence."""
    return f"policy action certainty for '{action}' p={p:.2f} (not artifact correctness)"


def from_nfet_and_contract(
    *,
    nfet_label: str = "",
    nfet_p: float = 0.0,
    green_hard: int = 0,
    total_hard: int = 0,
    validators_run: int = 0,
    validators_required: int = 0,
    capability_ok: bool = True,
    artifact_evidence_ok: bool = False,
) -> ConfidenceBundle:
    total = max(total_hard, 1)
    req = max(validators_required, 1)
    # Artifact correctness is evidence-driven, not policy p
    art = 0.0
    if artifact_evidence_ok and green_hard >= total_hard and total_hard > 0:
        art = 0.9
    elif green_hard > 0:
        art = min(0.7, green_hard / total)
    return ConfidenceBundle(
        policy_action_certainty=float(nfet_p or 0.0),
        policy_action_label=nfet_label or "",
        artifact_correctness_estimate=art,
        verification_coverage=min(1.0, validators_run / req),
        contract_completion=min(1.0, green_hard / total) if total_hard else 0.0,
        capability_feasibility=1.0 if capability_ok else 0.0,
        calibration_status="provisional",
    )
