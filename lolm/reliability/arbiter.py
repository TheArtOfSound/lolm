# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Evidence-Gated Controller Arbiter (EGCA).

All policy votes become inputs. Only EGCA executes an action.
Learned scores never override a hard evidence rule.

Hard precedence:
  safety → contradiction/infeasibility → rollback → deterministic closure →
  branch → verify → retrieve → continue
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# Binding actions the executor understands
ACTIONS = (
    "CLARIFY_OR_FAIL",
    "PROVISION_OR_WAIVE",
    "ROLLBACK",
    "FINALIZE_DETERMINISTICALLY",
    "BRANCH_WITH_CONSTRAINTS",
    "VERIFY",
    "RETRIEVE",
    "CONTINUE",
    "BLOCK_ACTION",  # e.g. blocked capability attempt
    "FREEZE_BUDGET",
)

PRECEDENCE = [
    "safety",
    "contradiction",
    "infeasibility",
    "rollback",
    "closure",
    "branch",
    "verify",
    "retrieve",
    "continue",
]


@dataclass
class ControllerVote:
    source: str  # task_state | nfet | verifier | capability | budget | safety | harness
    action: str  # desired action label
    weight: float = 1.0
    reason: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    soft: bool = True  # False = hard veto / hard force

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArbiterDecision:
    action: str
    reason: str
    votes: List[Dict[str, Any]] = field(default_factory=list)
    vetoes: List[str] = field(default_factory=list)
    rejected_alternatives: List[str] = field(default_factory=list)
    evidence_version: str = ""
    precedence_rule: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _evidence_version(state: Dict[str, Any]) -> str:
    raw = json.dumps(state, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def select_action(
    state: Dict[str, Any],
    votes: Sequence[ControllerVote],
) -> ArbiterDecision:
    """Select exactly one binding action from evidence + votes.

    Deterministic: same evidence state → same action.
    """
    votes_list = list(votes or [])
    vote_dicts = [v.to_dict() if isinstance(v, ControllerVote) else dict(v) for v in votes_list]
    evidence_version = _evidence_version({
        "contract_contradictory": state.get("contract_contradictory"),
        "hard_missing": state.get("hard_missing"),
        "regressed": state.get("regressed_from_green"),
        "closure_ready": state.get("closure_ready"),
        "failure_repeated": state.get("failure_repeated"),
        "causal_change_proposed": state.get("causal_change_proposed"),
        "verification_debt": state.get("verification_debt"),
        "retrieval_gain": state.get("retrieval_positive_gain"),
        "blocked_capability": state.get("blocked_capability"),
        "safety_violation": state.get("safety_violation"),
        "budget_frozen": state.get("budget_frozen"),
        "nonpositive_deltas": state.get("nonpositive_deltas"),
    })
    vetoes: List[str] = []
    rejected: List[str] = []
    ts = time.time()

    # 1. Safety
    if state.get("safety_violation"):
        return ArbiterDecision(
            action="BLOCK_ACTION",
            reason=f"safety violation: {state.get('safety_violation')}",
            votes=vote_dicts,
            vetoes=["all_execution"],
            evidence_version=evidence_version,
            precedence_rule="safety",
            payload={"violation": state.get("safety_violation")},
            ts=ts,
        )

    # 2. Contradiction / infeasibility
    if state.get("contract_contradictory"):
        return ArbiterDecision(
            action="CLARIFY_OR_FAIL",
            reason="contradictory contract — surface before artifact mutation",
            votes=vote_dicts,
            evidence_version=evidence_version,
            precedence_rule="contradiction",
            payload={"contradictions": state.get("contradictions") or []},
            ts=ts,
        )

    hard_missing = list(state.get("hard_missing") or [])
    if hard_missing:
        return ArbiterDecision(
            action="PROVISION_OR_WAIVE",
            reason=f"hard-missing capabilities: {hard_missing}",
            votes=vote_dicts,
            evidence_version=evidence_version,
            precedence_rule="infeasibility",
            payload={"hard_missing": hard_missing, "substitutes": state.get("substitutes") or {}},
            ts=ts,
        )

    # Capability attempt blocked (negative fact already definitive)
    if state.get("blocked_capability"):
        return ArbiterDecision(
            action="BLOCK_ACTION",
            reason=state.get("blocked_capability_reason")
                   or f"capability blocked: {state.get('blocked_capability')}",
            votes=vote_dicts,
            vetoes=[f"attempt:{state.get('blocked_capability')}"],
            evidence_version=evidence_version,
            precedence_rule="infeasibility",
            payload={
                "capability": state.get("blocked_capability"),
                "alternatives": state.get("capability_alternatives") or [],
            },
            ts=ts,
        )

    # 3. Rollback on green→red regression
    if state.get("regressed_from_green"):
        return ArbiterDecision(
            action="ROLLBACK",
            reason="workspace regressed from last-known-green checkpoint",
            votes=vote_dicts,
            vetoes=["accept_regression"],
            evidence_version=evidence_version,
            precedence_rule="rollback",
            payload={"checkpoint_id": state.get("last_green_id")},
            ts=ts,
        )

    # 4. Deterministic closure
    if state.get("closure_ready"):
        # Veto soft continue/verify votes from learned heads
        for v in vote_dicts:
            if v.get("action") in ("verify", "continue", "finalize") and v.get("soft", True):
                rejected.append(f"{v.get('source')}:{v.get('action')}")
        return ArbiterDecision(
            action="FINALIZE_DETERMINISTICALLY",
            reason="exact deliverable set verified; no model turn required",
            votes=vote_dicts,
            vetoes=["model_finalize"],
            rejected_alternatives=rejected,
            evidence_version=evidence_version,
            precedence_rule="closure",
            payload=dict(state.get("closure_payload") or {}),
            ts=ts,
        )

    # 5. Branch when failure repeated without causal change
    if state.get("failure_repeated") and not state.get("causal_change_proposed"):
        # Capability infeasibility + task-state branch votes outrank NFET verify
        return ArbiterDecision(
            action="BRANCH_WITH_CONSTRAINTS",
            reason="repeated root cause without causal lever change",
            votes=vote_dicts,
            vetoes=["verify_same_strategy", "retry_identical"],
            evidence_version=evidence_version,
            precedence_rule="branch",
            payload={
                "required_change": state.get("required_causal_change") or "strategy_vector",
                "root_cause": state.get("root_cause"),
            },
            ts=ts,
        )

    # Hard branch votes (task_state / harness) outrank soft NFET verify
    hard_branch = [
        v for v in votes_list
        if (getattr(v, "action", None) or (v.get("action") if isinstance(v, dict) else None))
        in ("branch", "BRANCH_WITH_CONSTRAINTS")
        and not (getattr(v, "soft", True) if not isinstance(v, dict) else v.get("soft", True))
    ]
    soft_verify = [
        v for v in votes_list
        if (getattr(v, "action", None) or (v.get("action") if isinstance(v, dict) else None))
        in ("verify", "VERIFY")
        and (getattr(v, "soft", True) if not isinstance(v, dict) else v.get("soft", True))
    ]
    if hard_branch and soft_verify and state.get("capability_infeasible"):
        return ArbiterDecision(
            action="BRANCH_WITH_CONSTRAINTS",
            reason="capability infeasibility vetoes verify; hard branch vote wins",
            votes=vote_dicts,
            vetoes=["nfet_verify"],
            rejected_alternatives=["VERIFY"],
            evidence_version=evidence_version,
            precedence_rule="branch",
            payload={"required_change": state.get("required_causal_change") or "verifier_or_schema"},
            ts=ts,
        )

    # 6. Verify debt
    if state.get("verification_debt"):
        return ArbiterDecision(
            action="VERIFY",
            reason="verification debt outstanding",
            votes=vote_dicts,
            evidence_version=evidence_version,
            precedence_rule="verify",
            payload={"debt": state.get("verification_debt")},
            ts=ts,
        )

    # Budget freeze on non-positive evidence deltas
    if state.get("budget_frozen") or (
        int(state.get("nonpositive_deltas") or 0) >= int(state.get("max_nonpositive") or 3)
    ):
        return ArbiterDecision(
            action="FREEZE_BUDGET",
            reason="N consecutive non-positive evidence deltas",
            votes=vote_dicts,
            evidence_version=evidence_version,
            precedence_rule="continue",
            payload={"nonpositive_deltas": state.get("nonpositive_deltas")},
            ts=ts,
        )

    # 7. Retrieve if positive expected gain
    if state.get("retrieval_positive_gain"):
        return ArbiterDecision(
            action="RETRIEVE",
            reason="retrieval has positive expected information gain",
            votes=vote_dicts,
            evidence_version=evidence_version,
            precedence_rule="retrieve",
            payload={"query": state.get("retrieval_query") or ""},
            ts=ts,
        )

    # 8. Highest-utility soft vote among remaining
    action_map = {
        "finalize": "CONTINUE",  # model finalize is not deterministic closure
        "branch": "BRANCH_WITH_CONSTRAINTS",
        "verify": "VERIFY",
        "retrieve": "RETRIEVE",
        "continue": "CONTINUE",
    }
    best: Optional[ControllerVote] = None
    best_score = -1.0
    for v in votes_list:
        act = getattr(v, "action", None) if not isinstance(v, dict) else v.get("action")
        weight = getattr(v, "weight", 1.0) if not isinstance(v, dict) else float(v.get("weight") or 1.0)
        soft = getattr(v, "soft", True) if not isinstance(v, dict) else v.get("soft", True)
        # Hard votes still count
        score = weight * (2.0 if not soft else 1.0)
        if score > best_score:
            best_score = score
            best = v if isinstance(v, ControllerVote) else ControllerVote(**{
                k: v[k] for k in ("source", "action", "weight", "reason", "soft") if k in v
            })

    if best is not None:
        raw = best.action
        mapped = action_map.get(raw, raw if raw in ACTIONS else "CONTINUE")
        return ArbiterDecision(
            action=mapped,
            reason=best.reason or f"highest utility vote from {best.source}",
            votes=vote_dicts,
            evidence_version=evidence_version,
            precedence_rule="continue",
            payload={"source": best.source},
            ts=ts,
        )

    return ArbiterDecision(
        action="CONTINUE",
        reason="no hard evidence rule; default continue",
        votes=vote_dicts,
        evidence_version=evidence_version,
        precedence_rule="continue",
        ts=ts,
    )
