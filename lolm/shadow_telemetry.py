# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Track 3 passive shadow-router telemetry.

The shadow router may recommend planner/executor/verifier assignments and
record counterfactual scores, but MUST NOT alter live model selection,
provider selection, tool access, retries, branch width, verification, or
shipping decisions until adaptive routing is explicitly enabled after all
gates pass.

Adaptive routing is hard-disabled by default.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from lolm.capability_router import (
    AgentRole,
    ModelCapability,
    ModelPerformance,
    RoutePlan,
    TaskProfile,
    default_registry,
    route_models,
)

# Hard gate — flip only after Track 1 real-traffic, Track 2B live-model, and
# per-bucket evidence requirements are met. Do not set True from product code.
ADAPTIVE_ROUTING_ENABLED = False

_MIN_OBSERVATIONS_PER_ROUTE = 30  # per candidate route per bucket

_DEFAULT_LOG = Path(
    os.environ.get(
        "LOLM_SHADOW_TELEMETRY_PATH",
        str(Path.home() / ".lolm" / "shadow_router_telemetry.jsonl"),
    )
)

_lock = threading.Lock()


@dataclass
class RoleSelection:
    planner: str = ""
    executor: str = ""
    verifier: str = ""

    @classmethod
    def from_route(cls, plan: RoutePlan) -> "RoleSelection":
        def mid(role: AgentRole) -> str:
            m = plan.model_for(role)
            return m.model_id if m else ""

        return cls(
            planner=mid(AgentRole.PLANNER),
            executor=mid(AgentRole.EXECUTOR),
            verifier=mid(AgentRole.VERIFIER),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "planner": self.planner,
            "executor": self.executor,
            "verifier": self.verifier,
        }


@dataclass
class ActualOutcome:
    verdict: str = "unknown"
    false_ship: bool = False
    rollback_required: bool = False
    unsupported_claims: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    # Retain all terminal classes for training (do not filter failures)
    terminal: str = ""  # verified_complete|failed|stuck|rejected|rolled_back|timed_out|abstained
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "false_ship": self.false_ship,
            "rollback_required": self.rollback_required,
            "unsupported_claims": self.unsupported_claims,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "terminal": self.terminal or self.verdict,
            "notes": self.notes,
        }


@dataclass
class ShadowRecord:
    """One passive shadow observation (schema: lolm.shadow_router.v1)."""
    schema: str = "lolm.shadow_router.v1"
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    ts: float = field(default_factory=time.time)
    task_bucket: str = ""
    baseline_selection: Dict[str, str] = field(default_factory=dict)
    shadow_router_selection: Dict[str, str] = field(default_factory=dict)
    router_scores: Dict[str, float] = field(default_factory=dict)
    router_reasons: List[str] = field(default_factory=list)
    actual_outcome: Dict[str, Any] = field(default_factory=dict)
    adaptive_routing_applied: bool = False
    adaptive_routing_enabled_flag: bool = False
    run_id: str = ""
    task_text_hash: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "record_id": self.record_id,
            "ts": self.ts,
            "task_bucket": self.task_bucket,
            "baseline_selection": self.baseline_selection,
            "shadow_router_selection": self.shadow_router_selection,
            "router_scores": self.router_scores,
            "router_reasons": self.router_reasons,
            "actual_outcome": self.actual_outcome,
            "adaptive_routing_applied": self.adaptive_routing_applied,
            "adaptive_routing_enabled_flag": self.adaptive_routing_enabled_flag,
            "run_id": self.run_id,
            "task_text_hash": self.task_text_hash,
            "meta": self.meta,
        }


def adaptive_routing_active() -> bool:
    """True only when hard flag is on AND env does not force shadow-only."""
    if not ADAPTIVE_ROUTING_ENABLED:
        return False
    # Extra kill-switch for production safety
    if os.environ.get("LOLM_FORCE_SHADOW_ONLY", "").strip() in ("1", "true", "yes"):
        return False
    return True


def _scores_from_route(plan: RoutePlan) -> Tuple[Dict[str, float], List[str]]:
    scores: Dict[str, float] = {}
    reasons: List[str] = []
    for item in plan.assignments:
        scores[item.role.value] = round(item.score, 6)
        reasons.append(f"{item.role.value}:{item.model_id}:{'|'.join(item.reasons[:4])}")
    return scores, reasons


class ShadowRouter:
    """Compute counterfactual routes and append-only telemetry.

    Never mutates live routing decisions when adaptive routing is disabled.
    """

    def __init__(
        self,
        *,
        log_path: Optional[Path] = None,
        registry: Optional[Sequence[ModelCapability]] = None,
    ) -> None:
        self.log_path = Path(log_path) if log_path else _DEFAULT_LOG
        self.registry = tuple(registry or default_registry())
        self._memory: List[ShadowRecord] = []

    def recommend(
        self,
        profile: TaskProfile,
        *,
        performance: Optional[Mapping[Tuple[str, str], ModelPerformance]] = None,
        available_models: Optional[Sequence[str]] = None,
    ) -> RoutePlan:
        """Shadow recommendation (may use measured performance). Not applied live."""
        return route_models(
            profile,
            registry=self.registry,
            performance=performance,
            available_models=available_models,
        )

    def baseline_route(
        self,
        profile: TaskProfile,
        *,
        available_models: Optional[Sequence[str]] = None,
        explicit: Optional[RoleSelection] = None,
    ) -> RoleSelection:
        """Conservative baseline used for live execution under passive mode.

        Uses registry priors only (no measured performance override) unless an
        explicit selection is provided by the caller.
        """
        if explicit is not None:
            return explicit
        plan = route_models(
            profile,
            registry=self.registry,
            performance=None,
            available_models=available_models,
        )
        return RoleSelection.from_route(plan)

    def open_observation(
        self,
        profile: TaskProfile,
        *,
        performance: Optional[Mapping[Tuple[str, str], ModelPerformance]] = None,
        available_models: Optional[Sequence[str]] = None,
        explicit_baseline: Optional[RoleSelection] = None,
        run_id: str = "",
        task_text_hash: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> ShadowRecord:
        """Open a shadow record at request start (outcome filled later)."""
        baseline = self.baseline_route(
            profile,
            available_models=available_models,
            explicit=explicit_baseline,
        )
        shadow_plan = self.recommend(
            profile,
            performance=performance,
            available_models=available_models,
        )
        scores, reasons = _scores_from_route(shadow_plan)
        rec = ShadowRecord(
            task_bucket=profile.bucket,
            baseline_selection=baseline.to_dict(),
            shadow_router_selection=RoleSelection.from_route(shadow_plan).to_dict(),
            router_scores=scores,
            router_reasons=reasons,
            actual_outcome={},
            adaptive_routing_applied=False,  # passive: never applied
            adaptive_routing_enabled_flag=adaptive_routing_active(),
            run_id=run_id or uuid.uuid4().hex[:12],
            task_text_hash=task_text_hash,
            meta=dict(meta or {}),
        )
        # Fail closed: even if flag were flipped incorrectly, product must pass
        # through apply_selection() which checks adaptive_routing_active().
        rec.adaptive_routing_applied = False
        return rec

    def complete_observation(
        self,
        rec: ShadowRecord,
        outcome: ActualOutcome,
        *,
        persist: bool = True,
    ) -> ShadowRecord:
        """Attach outcome and append to durable log. Never filters failures."""
        rec.actual_outcome = outcome.to_dict()
        rec.adaptive_routing_applied = False
        rec.adaptive_routing_enabled_flag = adaptive_routing_active()
        with _lock:
            self._memory.append(rec)
            if persist:
                self._append(rec)
        return rec

    def apply_selection_for_live(
        self,
        baseline: RoleSelection,
        shadow: RoleSelection,
    ) -> RoleSelection:
        """Return the selection that live execution must use.

        Passive mode always returns baseline. Adaptive mode (future) may
        return shadow only when adaptive_routing_active() is True.
        """
        if adaptive_routing_active():
            return shadow
        return baseline

    def _append(self, rec: ShadowRecord) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            # Telemetry must not break the agent path.
            pass

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with _lock:
            return [r.to_dict() for r in self._memory[-limit:]]


# Process-wide default for product integration
_default_shadow: Optional[ShadowRouter] = None


def get_shadow_router() -> ShadowRouter:
    global _default_shadow
    if _default_shadow is None:
        _default_shadow = ShadowRouter()
    return _default_shadow
