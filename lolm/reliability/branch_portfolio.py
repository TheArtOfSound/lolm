# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Counterfactual Branch Portfolio (CBP).

A branch is a set of genuinely different strategies, not another sample from
the same attractor. Hard feasibility filter precedes Pareto ranking.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

STRATEGY_DIMS = (
    "artifact_schema",
    "implementation_pattern",
    "dependency_plan",
    "tool_plan",
    "verifier_plan",
    "checkpoint_base",
)


@dataclass
class StrategyVector:
    artifact_schema: str = ""          # e.g. "single_html", "python_module", "pdf_report"
    implementation_pattern: str = ""   # e.g. "canvas_raf", "curses_ascii", "stdlib_http"
    dependency_plan: str = ""          # e.g. "stdlib_only", "pip:requests"
    tool_plan: str = ""                # e.g. "py_compile+run", "html.render", "xdg-open"
    verifier_plan: str = ""            # e.g. "static_html_lint", "unittest", "pdf.exists"
    checkpoint_base: str = ""          # checkpoint id this branch builds on
    predicted_information_gain: float = 0.0
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def dims(self) -> Dict[str, str]:
        return {d: getattr(self, d) or "" for d in STRATEGY_DIMS}

    def fingerprint(self) -> str:
        raw = "|".join(f"{d}={getattr(self, d) or ''}" for d in STRATEGY_DIMS)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def semantic_distance(a: StrategyVector, b: StrategyVector) -> float:
    """Categorical Hamming distance over strategy dimensions (0..1)."""
    da, db = a.dims(), b.dims()
    n = len(STRATEGY_DIMS)
    if n == 0:
        return 0.0
    changed = sum(1 for d in STRATEGY_DIMS if (da.get(d) or "") != (db.get(d) or ""))
    return changed / float(n)


def changed_levers(a: StrategyVector, b: StrategyVector) -> List[str]:
    da, db = a.dims(), b.dims()
    return [d for d in STRATEGY_DIMS if (da.get(d) or "") != (db.get(d) or "")]


@dataclass
class CandidateScore:
    candidate_id: str
    strategy: StrategyVector
    hard_ok: bool
    hard_failures: List[str] = field(default_factory=list)
    contract_coverage: float = 0.0
    verification_strength: float = 0.0
    novelty: float = 0.0
    cost: float = 0.0
    expected_information_gain: float = 0.0
    run_ok: Optional[bool] = None
    compile_ok: Optional[bool] = None
    diagnostic_only: bool = False
    why: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["strategy"] = self.strategy.to_dict()
        return d


def hard_feasibility_filter(
    candidates: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Two-stage selector stage 1: reject hard-infeasible candidates.

    A run-failed candidate can only be selected as an explicitly labeled
    diagnostic fallback when every candidate fails; it may never advance
    the green checkpoint.
    """
    feasible: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for c in candidates:
        hard_failures: List[str] = []
        if c.get("compile_ok") is False:
            hard_failures.append("does_not_compile")
        if c.get("run_ok") is False and c.get("require_run", True):
            hard_failures.append("run_failed")
        if c.get("path_ok") is False:
            hard_failures.append("wrong_path")
        if c.get("type_ok") is False:
            hard_failures.append("type_incompatible")
        if c.get("safety_ok") is False:
            hard_failures.append("safety")
        entry = dict(c)
        entry["hard_failures"] = hard_failures
        entry["hard_ok"] = not hard_failures
        if hard_failures:
            rejected.append(entry)
        else:
            feasible.append(entry)
    return feasible, rejected


def pareto_rank(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stage 2: rank by coverage, verification, novelty, cost, info gain."""
    def key(c: Dict[str, Any]) -> Tuple:
        return (
            float(c.get("contract_coverage") or 0.0),
            float(c.get("verification_strength") or 0.0),
            float(c.get("novelty") or 0.0),
            float(c.get("expected_information_gain") or 0.0),
            -float(c.get("cost") or 0.0),
        )
    return sorted(candidates, key=key, reverse=True)


def select_candidate(
    candidates: Sequence[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Hard filter then Pareto. Diagnostic fallback only if all fail."""
    feasible, rejected = hard_feasibility_filter(candidates)
    if feasible:
        ranked = pareto_rank(feasible)
        best = ranked[0]
        best = dict(best)
        best["diagnostic_only"] = False
        return best, "hard_feasible_pareto"
    if rejected:
        # Best diagnostic among failures — never advances green checkpoint
        # Prefer compile_ok over total mess
        def diag_key(c: Dict[str, Any]) -> Tuple:
            return (
                1 if c.get("compile_ok") else 0,
                1 if c.get("path_ok") else 0,
                float(c.get("contract_coverage") or 0.0),
            )
        best = dict(sorted(rejected, key=diag_key, reverse=True)[0])
        best["diagnostic_only"] = True
        best["why"] = "diagnostic_fallback_all_hard_failed"
        return best, "diagnostic_fallback"
    return None, "no_candidates"


class BranchPortfolio:
    """Track failed strategies and accept only diverse counterfactuals."""

    def __init__(self, min_distance: float = 0.34) -> None:
        self.min_distance = min_distance
        self.failed: List[StrategyVector] = []
        self.accepted: List[StrategyVector] = []

    def note_failure(self, strategy: StrategyVector) -> None:
        self.failed.append(strategy)

    def is_diverse(self, strategy: StrategyVector) -> Tuple[bool, str]:
        if not self.failed:
            return True, "no prior failures"
        for prev in self.failed:
            dist = semantic_distance(strategy, prev)
            if dist < self.min_distance:
                levers = changed_levers(strategy, prev)
                return False, (
                    f"semantic distance {dist:.2f} < {self.min_distance} "
                    f"vs failed strategy; changed_levers={levers or 'none'}"
                )
        return True, "sufficiently diverse"

    def accept_branch(
        self,
        strategy: StrategyVector,
        *,
        required_lever: Optional[str] = None,
    ) -> Tuple[bool, str]:
        ok, why = self.is_diverse(strategy)
        if not ok:
            return False, why
        # Wording-only: no dim changed vs last accepted
        if self.accepted:
            if semantic_distance(strategy, self.accepted[-1]) == 0.0:
                return False, "branch only changes source wording (identical strategy vector)"
        if required_lever:
            # Must change the required causal lever vs any failed with that issue
            if self.failed:
                last = self.failed[-1]
                levers = changed_levers(strategy, last)
                if required_lever not in levers:
                    return False, (
                        f"required causal lever '{required_lever}' not changed; "
                        f"changed={levers}"
                    )
        self.accepted.append(strategy)
        return True, "branch accepted"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_distance": self.min_distance,
            "failed": [s.to_dict() for s in self.failed],
            "accepted": [s.to_dict() for s in self.accepted],
        }
