# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Unified deterministic capability layer for LOLM agents.

This facade gives the existing chat and coding surfaces one integration point.
It does not call a language model. It decides which model roles are eligible,
which evidence contract applies, what repository context is relevant, and
whether a proposed command or answer may proceed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from lolm.capability_router import (
    ModelCapability,
    ModelPerformance,
    RoutePlan,
    TaskProfile,
    default_registry,
    route_models,
)
from lolm.command_preflight import (
    CommandPreflight,
    ShellDialect,
    VerifierPlan,
    inspect_command,
    verifier_plan,
)
from lolm.grounded_qa import (
    EvidencePassage,
    GroundedAnswer,
    GroundingPolicy,
    GroundingReport,
    grounding_policy,
    validate_grounded_answer,
)
from lolm.repo_context import (
    ContextSelection,
    RepositoryMap,
    SourceDocument,
    build_repository_map,
    rank_repository_context,
)
from lolm.mutation_gateway import MutationGateway
from lolm.shadow_telemetry import (
    ActualOutcome,
    ShadowRecord,
    ShadowRouter,
    adaptive_routing_active,
    get_shadow_router,
)
from lolm.task_profiler import profile_task


@dataclass(frozen=True)
class RequestDecision:
    profile: TaskProfile
    route: RoutePlan
    grounding: GroundingPolicy
    shadow: Optional[ShadowRecord] = None
    shadow_route: Optional[RoutePlan] = None

    def to_dict(self) -> dict:
        return {
            "profile": self.route.to_dict()["profile"],
            "route": self.route.to_dict(),
            "shadow_route": self.shadow_route.to_dict() if self.shadow_route else None,
            "shadow_record": self.shadow.to_dict() if self.shadow else None,
            "adaptive_routing_applied": False if not adaptive_routing_active() else (
                bool(self.shadow and self.shadow.adaptive_routing_applied)
            ),
            "grounding": {
                "mode": self.grounding.mode.value,
                "require_claim_ledger": self.grounding.require_claim_ledger,
                "require_citations": self.grounding.require_citations,
                "require_fresh_sources": self.grounding.require_fresh_sources,
                "max_source_age_days": self.grounding.max_source_age_days,
                "minimum_coverage": self.grounding.minimum_coverage,
            },
        }


@dataclass(frozen=True)
class CommandDecision:
    preflight: CommandPreflight
    verifier_candidates: Tuple[VerifierPlan, ...]

    @property
    def allowed(self) -> bool:
        return self.preflight.accepted

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "preflight": self.preflight.to_dict(),
            "verifier_candidates": [
                {
                    "verifier": item.verifier,
                    "command": item.command,
                    "internal": item.internal,
                    "evidence_kind": item.evidence_kind,
                }
                for item in self.verifier_candidates
            ],
        }


@dataclass(frozen=True)
class RepositoryDecision:
    repository_map: RepositoryMap
    context: ContextSelection

    def to_dict(self) -> dict:
        return {
            "used_tokens": self.context.used_tokens,
            "budget_tokens": self.context.budget_tokens,
            "selected": [
                {
                    "path": item.path,
                    "score": round(item.score, 6),
                    "reason": list(item.reason),
                    "estimated_tokens": item.estimated_tokens,
                    "symbols": list(item.symbols),
                    "excerpt": item.excerpt,
                }
                for item in self.context.items
            ],
            "omitted_paths": list(self.context.omitted_paths),
            "file_count": len(self.repository_map.files),
        }


@dataclass
class CapabilityTelemetry:
    events: List[dict] = field(default_factory=list)

    def record(self, event: str, **data: object) -> dict:
        payload = {"event": event, "data": data}
        self.events.append(payload)
        return payload


class AgentCapabilityCore:
    """Deterministic policy and verification facade.

    Instances are cheap and request-safe. Provider health/performance stores can
    be passed per call until a durable routing database is connected.
    """

    def __init__(
        self,
        *,
        registry: Optional[Sequence[ModelCapability]] = None,
        telemetry: Optional[CapabilityTelemetry] = None,
        shadow: Optional[ShadowRouter] = None,
    ) -> None:
        self.registry = tuple(registry or default_registry())
        self.telemetry = telemetry or CapabilityTelemetry()
        self.shadow = shadow or get_shadow_router()

    def prepare_request(
        self,
        text: str,
        *,
        has_repository: bool = False,
        supplied_sources: bool = False,
        source_constrained: bool = False,
        available_models: Optional[Iterable[str]] = None,
        performance: Optional[Mapping[Tuple[str, str], ModelPerformance]] = None,
        run_id: str = "",
        persist_shadow: bool = True,
    ) -> RequestDecision:
        profile = profile_task(
            text,
            has_repository=has_repository,
            supplied_sources=supplied_sources,
        )
        # Shadow recommendation may use measured performance (counterfactual only).
        shadow_route = route_models(
            profile,
            registry=self.registry,
            performance=performance,
            available_models=available_models,
        )
        # Live baseline: registry priors only while adaptive routing is disabled.
        # When adaptive routing is enabled (future), live may follow shadow_route.
        if adaptive_routing_active():
            route = shadow_route
            adaptive_applied = True
        else:
            route = route_models(
                profile,
                registry=self.registry,
                performance=None,
                available_models=available_models,
            )
            adaptive_applied = False

        shadow_rec = self.shadow.open_observation(
            profile,
            performance=performance,
            available_models=list(available_models) if available_models is not None else None,
            run_id=run_id,
            task_text_hash=str(abs(hash(text or "")))[:16],
            meta={"adaptive_applied": adaptive_applied},
        )
        # Open observation is not completed until record_outcome(); still persist open
        # so passive mode has request-start counters even if outcome never arrives.
        if persist_shadow:
            try:
                self.shadow._append(shadow_rec)
            except Exception:
                pass

        evidence_policy = grounding_policy(
            profile,
            supplied_sources=supplied_sources,
            source_constrained=source_constrained,
        )
        decision = RequestDecision(
            profile, route, evidence_policy,
            shadow=shadow_rec, shadow_route=shadow_route,
        )
        self.telemetry.record(
            "request_profiled",
            kind=profile.kind.value,
            language=profile.language,
            bucket=profile.bucket,
            route=route.to_dict()["assignments"],
            shadow_route=shadow_route.to_dict()["assignments"],
            adaptive_routing_applied=adaptive_applied,
            grounding_mode=evidence_policy.mode.value,
        )
        self.telemetry.record(
            "shadow_router_observation",
            record_id=shadow_rec.record_id,
            task_bucket=shadow_rec.task_bucket,
            baseline_selection=shadow_rec.baseline_selection,
            shadow_router_selection=shadow_rec.shadow_router_selection,
            router_scores=shadow_rec.router_scores,
            adaptive_routing_applied=False,
        )
        return decision

    def record_run_outcome(
        self,
        decision: RequestDecision,
        *,
        verdict: str,
        false_ship: bool = False,
        rollback_required: bool = False,
        unsupported_claims: int = 0,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
        terminal: str = "",
        notes: str = "",
    ) -> Optional[ShadowRecord]:
        """Complete passive shadow observation with actual verifier/repo evidence."""
        if not decision.shadow:
            return None
        outcome = ActualOutcome(
            verdict=verdict,
            false_ship=false_ship,
            rollback_required=rollback_required,
            unsupported_claims=unsupported_claims,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            terminal=terminal or verdict,
            notes=notes,
        )
        completed = self.shadow.complete_observation(decision.shadow, outcome)
        self.telemetry.record(
            "shadow_router_outcome",
            record_id=completed.record_id,
            task_bucket=completed.task_bucket,
            actual_outcome=completed.actual_outcome,
            adaptive_routing_applied=False,
        )
        return completed

    def prepare_command(
        self,
        command: str,
        *,
        artifact_path: str = "",
        primary_language: str = "",
        known_files: Optional[Sequence[str]] = None,
        shell: str | ShellDialect = ShellDialect.POSIX_SH,
    ) -> CommandDecision:
        preflight = inspect_command(
            command,
            shell=shell,
            primary_language=primary_language,
            known_files=known_files,
        )
        plans = verifier_plan(artifact_path, primary_language=primary_language) if artifact_path else tuple()
        decision = CommandDecision(preflight, tuple(plans))
        self.telemetry.record(
            "command_preflight",
            accepted=preflight.accepted,
            failure_class=preflight.primary_failure.value,
            fingerprint=preflight.fingerprint,
            executable=preflight.executable,
            verifier_candidates=[item.verifier for item in plans],
        )
        return decision

    def prepare_repository(
        self,
        query: str,
        documents: Sequence[SourceDocument],
        *,
        changed_paths: Optional[Iterable[str]] = None,
        failing_paths: Optional[Iterable[str]] = None,
        token_budget: int = 4000,
        max_files: int = 12,
    ) -> RepositoryDecision:
        repository_map = build_repository_map(documents)
        context = rank_repository_context(
            query,
            documents,
            repository_map,
            changed_paths=changed_paths,
            failing_paths=failing_paths,
            token_budget=token_budget,
            max_files=max_files,
        )
        decision = RepositoryDecision(repository_map, context)
        self.telemetry.record(
            "repository_context_selected",
            file_count=len(repository_map.files),
            selected_paths=[item.path for item in context.items],
            used_tokens=context.used_tokens,
            budget_tokens=context.budget_tokens,
        )
        return decision

    def verify_answer(
        self,
        answer: GroundedAnswer,
        evidence: Sequence[EvidencePassage],
        policy: GroundingPolicy,
        *,
        support_fn=None,
        support_threshold: float = 0.55,
        now: Optional[datetime] = None,
    ) -> GroundingReport:
        report = validate_grounded_answer(
            answer,
            evidence,
            policy,
            support_fn=support_fn,
            support_threshold=support_threshold,
            now=now,
        )
        self.telemetry.record(
            "answer_grounding_verified",
            valid=report.valid,
            coverage=report.coverage,
            unsupported_claim_rate=report.unsupported_claim_rate,
            citation_entailment_rate=report.citation_entailment_rate,
            errors=list(report.errors),
        )
        return report
