# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Evidence Progress Budget.

Allocate steps when expected information gain or contract coverage improves;
freeze budget on repeated root causes; reserve steps for rollback/finalization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActionDelta:
    step: int
    action: str
    contract_coverage_delta: float = 0.0
    verifier_delta: float = 0.0
    information_gain: float = 0.0
    error_novelty: float = 0.0
    cost: float = 1.0

    @property
    def positive(self) -> bool:
        return (
            self.contract_coverage_delta > 0
            or self.verifier_delta > 0
            or self.information_gain > 0
            or self.error_novelty > 0
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvidenceProgressBudget:
    def __init__(
        self,
        max_steps: int = 18,
        *,
        max_nonpositive: int = 3,
        reserve_for_finalize: int = 2,
    ) -> None:
        self.max_steps = max_steps
        self.max_nonpositive = max_nonpositive
        self.reserve_for_finalize = reserve_for_finalize
        self.used = 0
        self.deltas: List[ActionDelta] = []
        self.nonpositive_streak = 0
        self.frozen = False
        self.freeze_reason = ""

    def remaining(self) -> int:
        return max(0, self.max_steps - self.used)

    def reserve_ok(self) -> bool:
        """Keep reserve steps for rollback/finalization when possible."""
        return self.remaining() > self.reserve_for_finalize or self.frozen

    def record(self, delta: ActionDelta) -> None:
        self.deltas.append(delta)
        self.used += 1
        if delta.positive:
            self.nonpositive_streak = 0
            if self.frozen and delta.positive:
                # Unfreeze only on declared causal improvement
                self.frozen = False
                self.freeze_reason = ""
        else:
            self.nonpositive_streak += 1
            if self.nonpositive_streak >= self.max_nonpositive:
                self.frozen = True
                self.freeze_reason = (
                    f"{self.nonpositive_streak} consecutive non-positive evidence deltas"
                )

    def may_generate(self, *, causal_lever_changed: bool = False) -> tuple:
        if self.used >= self.max_steps:
            return False, "step budget exhausted"
        if self.frozen and not causal_lever_changed:
            return False, (
                self.freeze_reason
                + " — next action must change a declared causal lever"
            )
        return True, "ok"

    def outcome_attribution(self) -> Dict[str, Any]:
        pos = sum(1 for d in self.deltas if d.positive)
        return {
            "actions": len(self.deltas),
            "positive_delta_actions": pos,
            "nonpositive_streak": self.nonpositive_streak,
            "frozen": self.frozen,
            "utility_rate": (pos / len(self.deltas)) if self.deltas else 0.0,
            "deltas": [d.to_dict() for d in self.deltas[-30:]],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "used": self.used,
            "remaining": self.remaining(),
            "nonpositive_streak": self.nonpositive_streak,
            "frozen": self.frozen,
            "freeze_reason": self.freeze_reason,
            "outcome_attribution": self.outcome_attribution(),
        }
