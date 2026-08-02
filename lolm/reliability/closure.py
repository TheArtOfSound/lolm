# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Artifact Closure Protocol (ACP).

When the exact deliverable set exists, hashes match, required validators are
green, and no hard criterion remains open, the harness finalizes without
another model turn.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class ClosureResult:
    ready: bool
    reason: str
    closed: bool = False
    checkpoint_id: str = ""
    manifest: Dict[str, Any] = field(default_factory=dict)
    blocked_model_turns: int = 0
    preconditions: Dict[str, bool] = field(default_factory=dict)
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_closure(
    *,
    contract_ok: bool,
    exact_manifest_ok: bool,
    validators_green: bool,
    open_hard: int,
    contradictory: bool = False,
    receipt_signable: bool = True,
    deliverable_paths: Optional[Sequence[str]] = None,
    path_hashes: Optional[Dict[str, str]] = None,
) -> ClosureResult:
    """Pure predicate: are closure preconditions satisfied?"""
    pre = {
        "contract_ok": bool(contract_ok),
        "exact_manifest_ok": bool(exact_manifest_ok),
        "validators_green": bool(validators_green),
        "no_open_hard": int(open_hard or 0) == 0,
        "not_contradictory": not contradictory,
        "receipt_signable": bool(receipt_signable),
        "has_deliverables": bool(deliverable_paths),
    }
    ready = all(pre.values())
    if ready:
        reason = "all closure preconditions met"
    else:
        failed = [k for k, v in pre.items() if not v]
        reason = "not ready: " + ", ".join(failed)
    return ClosureResult(
        ready=ready,
        reason=reason,
        preconditions=pre,
        manifest={
            "paths": list(deliverable_paths or []),
            "hashes": dict(path_hashes or {}),
        },
        ts=time.time(),
    )


class ClosureProtocol:
    """Stateful closure transaction: freeze, export, block further model turns."""

    def __init__(self) -> None:
        self.closed = False
        self.result: Optional[ClosureResult] = None
        self.model_turns_blocked = 0
        self.writes_blocked = 0
        self.closure_step: Optional[int] = None

    def try_close(
        self,
        evaluation: ClosureResult,
        *,
        checkpoint_id: str = "",
        step: int = 0,
    ) -> ClosureResult:
        if self.closed:
            evaluation.closed = True
            evaluation.blocked_model_turns = self.model_turns_blocked
            evaluation.checkpoint_id = self.result.checkpoint_id if self.result else checkpoint_id
            return evaluation
        if not evaluation.ready:
            self.result = evaluation
            return evaluation
        evaluation.closed = True
        evaluation.checkpoint_id = checkpoint_id
        self.closed = True
        self.result = evaluation
        self.closure_step = step
        return evaluation

    def allow_model_turn(self) -> bool:
        """After closure, zero additional model generations unless invalidated."""
        if self.closed:
            self.model_turns_blocked += 1
            return False
        return True

    def allow_write(self) -> bool:
        if self.closed:
            self.writes_blocked += 1
            return False
        return True

    def invalidate(self, reason: str = "") -> None:
        """Verifier invalidated the artifact — reopen loop."""
        self.closed = False
        if self.result:
            self.result.closed = False
            self.result.ready = False
            self.result.reason = f"invalidated: {reason}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "closed": self.closed,
            "closure_step": self.closure_step,
            "model_turns_blocked": self.model_turns_blocked,
            "writes_blocked": self.writes_blocked,
            "result": self.result.to_dict() if self.result else None,
        }
