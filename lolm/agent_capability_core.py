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
from lolm.task_profiler import profile_task


@dataclass(frozen=True)
class RequestDecision:
    profile: TaskProfile
    route: RoutePlan
    grounding: GroundingPolicy

    def to_dict(self) -> dict:
        return {
            "profile": self.route.to_dict()["profile"],
            "route": self.route.to_dict(),
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
    ) -> None:
        self.registry = tuple(registry or default_registry())
        self.telemetry = telemetry or CapabilityTelemetry()

    def prepare_request(
        self,
        text: str,
        *,
        has_repository: bool = False,
        supplied_sources: bool = False,
        source_constrained: bool = False,
        available_models: Optional[Iterable[str]] = None,
        performance: Optional[Mapping[Tuple[str, str], ModelPerformance]] = None,
    ) -> RequestDecision:
        profile = profile_task(
            text,
            has_repository=has_repository,
            supplied_sources=supplied_sources,
        )
        route = route_models(
            profile,
            registry=self.registry,
            performance=performance,
            available_models=available_models,
        )
        evidence_policy = grounding_policy(
            profile,
            supplied_sources=supplied_sources,
            source_constrained=source_constrained,
        )
        decision = RequestDecision(profile, route, evidence_policy)
        self.telemetry.record(
            "request_profiled",
            kind=profile.kind.value,
            language=profile.language,
            bucket=profile.bucket,
            route=route.to_dict()["assignments"],
            grounding_mode=evidence_policy.mode.value,
        )
        return decision

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
