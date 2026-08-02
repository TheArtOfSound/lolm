# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Capability-based routing for LOLM agent roles.

A static list of allegedly strong models is not a router. This module separates:

* task profiling and hard requirements;
* model capability metadata;
* measured rolling performance;
* role-specific selection for planner, executor, and verifier.

The built-in model values are deliberately conservative *priors*, not benchmark
claims. Production routing should be dominated by measured outcomes from LOLM's
own task buckets and provider health.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class TaskKind(str, Enum):
    CHAT = "chat"
    FACTUAL_QA = "factual_qa"
    CURRENT_QA = "current_qa"
    RESEARCH = "research"
    CODE_GENERATION = "code_generation"
    REPO_EDIT = "repo_edit"
    SHELL_OPERATION = "shell_operation"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


class AgentRole(str, Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    VERIFIER = "verifier"


@dataclass(frozen=True)
class TaskProfile:
    kind: TaskKind
    language: str = ""
    requires_tools: bool = False
    requires_execution: bool = False
    requires_retrieval: bool = False
    requires_current_information: bool = False
    requires_structured_output: bool = False
    repository_context: bool = False
    estimated_context_tokens: int = 0
    risk: float = 0.0
    tags: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def bucket(self) -> str:
        language = self.language or "any"
        return f"{self.kind.value}:{language}"


@dataclass(frozen=True)
class ModelCapability:
    model_id: str
    provider: str
    context_tokens: int
    reasoning: float
    coding: float
    repo_editing: float
    tool_use: float
    structured_output: float
    factuality: float
    verification: float
    latency: float
    cost: float
    languages: Tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    source: str = "registry_prior"

    def supports_language(self, language: str) -> bool:
        if not language or not self.languages:
            return True
        normalized = language.lower()
        return normalized in {value.lower() for value in self.languages}


@dataclass(frozen=True)
class ModelPerformance:
    model_id: str
    bucket: str
    attempts: int = 0
    pass_rate: float = 0.5
    format_error_rate: float = 0.0
    tool_error_rate: float = 0.0
    timeout_rate: float = 0.0
    unsupported_claim_rate: float = 0.0
    mean_latency_ms: float = 0.0

    @property
    def confidence(self) -> float:
        # Saturates gradually; five successes must not overrule a broad prior.
        return 1.0 - math.exp(-max(self.attempts, 0) / 40.0)

    @property
    def reliability(self) -> float:
        penalties = (
            0.30 * self.format_error_rate
            + 0.30 * self.tool_error_rate
            + 0.20 * self.timeout_rate
            + 0.20 * self.unsupported_claim_rate
        )
        return min(max(self.pass_rate - penalties, 0.0), 1.0)


@dataclass(frozen=True)
class RoutedModel:
    role: AgentRole
    model_id: str
    provider: str
    score: float
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class RoutePlan:
    profile: TaskProfile
    assignments: Tuple[RoutedModel, ...]
    rejected: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    def model_for(self, role: AgentRole) -> Optional[RoutedModel]:
        return next((item for item in self.assignments if item.role == role), None)

    def to_dict(self) -> dict:
        return {
            "profile": {
                "kind": self.profile.kind.value,
                "language": self.profile.language,
                "bucket": self.profile.bucket,
                "requires_tools": self.profile.requires_tools,
                "requires_execution": self.profile.requires_execution,
                "requires_retrieval": self.profile.requires_retrieval,
                "requires_current_information": self.profile.requires_current_information,
                "requires_structured_output": self.profile.requires_structured_output,
                "repository_context": self.profile.repository_context,
                "estimated_context_tokens": self.profile.estimated_context_tokens,
                "risk": self.profile.risk,
                "tags": list(self.profile.tags),
            },
            "assignments": [
                {
                    "role": item.role.value,
                    "model_id": item.model_id,
                    "provider": item.provider,
                    "score": round(item.score, 6),
                    "reasons": list(item.reasons),
                }
                for item in self.assignments
            ],
            "rejected": [{"model_id": model_id, "reason": reason} for model_id, reason in self.rejected],
        }


_CURRENT_RE = re.compile(
    r"\b(today|current|currently|latest|newest|now|this\s+(?:week|month|year)|"
    r"price|score|weather|released|release\s+date|ceo|president|version)\b",
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(r"\b(research|compare|sources?|citations?|evidence|paper|survey|benchmark)\b", re.I)
_REPO_RE = re.compile(r"\b(repo(?:sitory)?|pull request|commit|branch|issue|codebase|existing project|git diff)\b", re.I)
_SHELL_RE = re.compile(r"\b(shell|terminal|command|cli|bash|powershell|cmd\.exe|run this|execute)\b", re.I)
_CODE_RE = re.compile(
    r"\b(code|function|class|module|script|api|bug|debug|implement|compile|test|"
    r"html|css|javascript|typescript|python|rust|golang|java|sql)\b",
    re.IGNORECASE,
)
_DOCUMENT_RE = re.compile(r"\b(pdf|docx|document|report|proposal|resume|spreadsheet|slides?)\b", re.I)
_QUESTION_RE = re.compile(r"\?|\b(what|why|how|when|where|who|which|is|are|does|do|can)\b", re.I)


def _detect_language(text: str) -> str:
    lower = text.lower()
    checks = (
        ("html", ("index.html", " html", "<html", "canvas", "browser-native")),
        ("typescript", ("typescript", ".ts", ".tsx")),
        ("javascript", ("javascript", "node.js", ".js", ".mjs", ".cjs")),
        ("python", ("python", ".py", "pytest", "unittest")),
        ("rust", ("rust", "cargo", ".rs")),
        ("go", ("golang", " go ", "go.mod", ".go")),
        ("java", ("java", "maven", "gradle", ".java")),
        ("sql", ("sql", "database query", ".sql")),
    )
    for language, needles in checks:
        if any(needle in lower for needle in needles):
            return language
    return ""


def profile_task(text: str, *, has_repository: bool = False, supplied_sources: bool = False) -> TaskProfile:
    """Deterministic fallback profiler.

    A learned classifier may replace or override this output. The fallback is
    intentionally auditable and emits requirements instead of just one label.
    """
    content = (text or "").strip()
    language = _detect_language(content)
    current = bool(_CURRENT_RE.search(content))
    repo = has_repository or bool(_REPO_RE.search(content))
    shell = bool(_SHELL_RE.search(content))
    code = bool(_CODE_RE.search(content))
    research = bool(_RESEARCH_RE.search(content))
    document = bool(_DOCUMENT_RE.search(content))
    question = bool(_QUESTION_RE.search(content))

    if repo and code:
        kind = TaskKind.REPO_EDIT
    elif code:
        kind = TaskKind.CODE_GENERATION
    elif shell:
        kind = TaskKind.SHELL_OPERATION
    elif research:
        kind = TaskKind.RESEARCH
    elif current and question:
        kind = TaskKind.CURRENT_QA
    elif question:
        kind = TaskKind.FACTUAL_QA
    elif document:
        kind = TaskKind.DOCUMENT
    elif len(content.split()) <= 12:
        kind = TaskKind.CHAT
    else:
        kind = TaskKind.UNKNOWN

    requires_execution = kind in {TaskKind.CODE_GENERATION, TaskKind.REPO_EDIT, TaskKind.SHELL_OPERATION}
    requires_tools = requires_execution or kind in {TaskKind.CURRENT_QA, TaskKind.RESEARCH, TaskKind.DOCUMENT}
    requires_retrieval = supplied_sources or current or kind in {TaskKind.RESEARCH, TaskKind.REPO_EDIT}
    structured = requires_execution or kind == TaskKind.DOCUMENT
    risk = 0.15
    if kind == TaskKind.SHELL_OPERATION:
        risk = 0.70
    elif kind == TaskKind.REPO_EDIT:
        risk = 0.55
    elif current:
        risk = 0.40

    tags: List[str] = []
    if current:
        tags.append("freshness")
    if repo:
        tags.append("repository")
    if shell:
        tags.append("shell")
    if supplied_sources:
        tags.append("supplied_sources")

    estimated = max(512, min(len(content) * 3, 200_000))
    return TaskProfile(
        kind=kind,
        language=language,
        requires_tools=requires_tools,
        requires_execution=requires_execution,
        requires_retrieval=requires_retrieval,
        requires_current_information=current,
        requires_structured_output=structured,
        repository_context=repo,
        estimated_context_tokens=estimated,
        risk=risk,
        tags=tuple(tags),
    )


def default_registry() -> Tuple[ModelCapability, ...]:
    """Initial benchmark candidates with conservative capability priors.

    Values are routing priors only. They must be replaced by measured per-bucket
    results before production promotion.
    """
    return (
        ModelCapability(
            "Qwen/Qwen3-Coder-30B-A3B-Instruct", "huggingface", 131_072,
            reasoning=0.72, coding=0.86, repo_editing=0.78, tool_use=0.76,
            structured_output=0.75, factuality=0.62, verification=0.70,
            latency=0.72, cost=0.78,
            languages=("python", "javascript", "typescript", "html", "go", "rust", "java", "sql"),
        ),
        ModelCapability(
            "Qwen/Qwen3-Coder-480B-A35B-Instruct", "huggingface", 131_072,
            reasoning=0.88, coding=0.93, repo_editing=0.90, tool_use=0.86,
            structured_output=0.82, factuality=0.69, verification=0.84,
            latency=0.30, cost=0.30,
            languages=("python", "javascript", "typescript", "html", "go", "rust", "java", "sql"),
        ),
        ModelCapability(
            "mistralai/Devstral-Small-2507", "huggingface", 131_072,
            reasoning=0.75, coding=0.84, repo_editing=0.86, tool_use=0.78,
            structured_output=0.72, factuality=0.61, verification=0.74,
            latency=0.70, cost=0.72,
            languages=("python", "javascript", "typescript", "html", "go", "rust", "java"),
        ),
        ModelCapability(
            "moonshotai/Kimi-K2-Instruct", "huggingface", 131_072,
            reasoning=0.90, coding=0.86, repo_editing=0.84, tool_use=0.90,
            structured_output=0.82, factuality=0.78, verification=0.83,
            latency=0.28, cost=0.28,
        ),
        ModelCapability(
            "zai-org/GLM-4.5", "huggingface", 131_072,
            reasoning=0.86, coding=0.84, repo_editing=0.80, tool_use=0.84,
            structured_output=0.80, factuality=0.72, verification=0.80,
            latency=0.42, cost=0.45,
        ),
        ModelCapability(
            "openai/gpt-oss-120b", "huggingface", 131_072,
            reasoning=0.84, coding=0.82, repo_editing=0.78, tool_use=0.76,
            structured_output=0.77, factuality=0.73, verification=0.80,
            latency=0.55, cost=0.58,
        ),
        ModelCapability(
            "ibm-granite/granite-3.3-8b-instruct", "huggingface", 32_768,
            reasoning=0.58, coding=0.55, repo_editing=0.45, tool_use=0.62,
            structured_output=0.68, factuality=0.62, verification=0.58,
            latency=0.93, cost=0.94,
        ),
    )


def _hard_rejection(profile: TaskProfile, model: ModelCapability, role: AgentRole) -> str:
    if not model.enabled:
        return "disabled"
    if model.context_tokens < max(profile.estimated_context_tokens, 1):
        return "insufficient_context"
    if not model.supports_language(profile.language):
        return "language_not_supported"
    if profile.requires_structured_output and model.structured_output < 0.55:
        return "structured_output_below_floor"
    if profile.requires_tools and role == AgentRole.EXECUTOR and model.tool_use < 0.60:
        return "tool_use_below_floor"
    if profile.kind in {TaskKind.CODE_GENERATION, TaskKind.REPO_EDIT} and role == AgentRole.EXECUTOR:
        if model.coding < 0.65:
            return "coding_below_floor"
    if profile.kind == TaskKind.REPO_EDIT and role in {AgentRole.PLANNER, AgentRole.EXECUTOR}:
        if model.repo_editing < 0.60:
            return "repo_editing_below_floor"
    if role == AgentRole.VERIFIER and model.verification < 0.55:
        return "verification_below_floor"
    return ""


def _prior_score(profile: TaskProfile, model: ModelCapability, role: AgentRole) -> float:
    if role == AgentRole.PLANNER:
        score = 0.45 * model.reasoning + 0.20 * model.factuality + 0.15 * model.structured_output
        if profile.repository_context:
            score += 0.20 * model.repo_editing
        else:
            score += 0.20 * model.coding if profile.requires_execution else 0.20 * model.reasoning
    elif role == AgentRole.EXECUTOR:
        score = 0.34 * model.tool_use + 0.30 * model.structured_output + 0.20 * model.coding
        score += 0.16 * (model.repo_editing if profile.repository_context else model.reasoning)
    else:
        score = 0.45 * model.verification + 0.25 * model.reasoning + 0.20 * model.factuality
        score += 0.10 * model.structured_output
    # Cost/latency matter, but never enough to beat an incapable model.
    score += 0.04 * model.latency + 0.04 * model.cost
    return min(max(score, 0.0), 1.0)


def _performance_for(
    model_id: str,
    bucket: str,
    performance: Mapping[Tuple[str, str], ModelPerformance],
) -> Optional[ModelPerformance]:
    return performance.get((model_id, bucket)) or performance.get((model_id, "*"))


def route_models(
    profile: TaskProfile,
    *,
    registry: Optional[Sequence[ModelCapability]] = None,
    performance: Optional[Mapping[Tuple[str, str], ModelPerformance]] = None,
    available_models: Optional[Iterable[str]] = None,
) -> RoutePlan:
    """Select independent planner, executor, and verifier assignments."""
    models = tuple(registry or default_registry())
    perf = performance or {}
    available: Optional[Set[str]] = set(available_models) if available_models is not None else None
    assignments: List[RoutedModel] = []
    rejected: List[Tuple[str, str]] = []

    for role in (AgentRole.PLANNER, AgentRole.EXECUTOR, AgentRole.VERIFIER):
        candidates: List[Tuple[float, ModelCapability, Tuple[str, ...]]] = []
        for model in models:
            if available is not None and model.model_id not in available:
                rejected.append((model.model_id, "provider_unavailable"))
                continue
            rejection = _hard_rejection(profile, model, role)
            if rejection:
                rejected.append((model.model_id, f"{role.value}:{rejection}"))
                continue

            prior = _prior_score(profile, model, role)
            observed = _performance_for(model.model_id, profile.bucket, perf)
            reasons = [f"prior={prior:.3f}"]
            score = prior
            if observed is not None:
                weight = observed.confidence
                score = (1.0 - weight) * prior + weight * observed.reliability
                reasons.extend((
                    f"measured={observed.reliability:.3f}",
                    f"attempts={observed.attempts}",
                    f"measurement_weight={weight:.3f}",
                ))

            if role == AgentRole.VERIFIER and assignments:
                executor = next((a for a in assignments if a.role == AgentRole.EXECUTOR), None)
                planner = next((a for a in assignments if a.role == AgentRole.PLANNER), None)
                if executor and model.model_id == executor.model_id:
                    score -= 0.30
                    reasons.append("same_model_verifier_penalty=-0.300")
                elif executor and model.provider == executor.provider:
                    score -= 0.10
                    reasons.append("same_provider_verifier_penalty=-0.100")
                if planner and model.model_id == planner.model_id:
                    score -= 0.08
                    reasons.append("planner_verifier_correlation_penalty=-0.080")

            candidates.append((score, model, tuple(reasons)))

        if not candidates:
            continue
        candidates.sort(key=lambda item: (item[0], item[1].model_id), reverse=True)
        score, model, reasons = candidates[0]
        assignments.append(RoutedModel(role, model.model_id, model.provider, score, reasons))

    return RoutePlan(profile, tuple(assignments), tuple(rejected))
