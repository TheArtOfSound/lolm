# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Grounded question-answering primitives for LOLM.

This module makes factuality a contract rather than a writing preference. A
writer model produces claim records; retrieval supplies identified passages;
and a separate verifier validates citation coverage, source existence,
freshness, and support. Model confidence is never accepted as evidence.

Dense retrieval and NLI/reranking are injected as scores/callbacks so the core
remains deterministic and testable. Recommended production candidates are
BAAI/bge-m3 for retrieval and BAAI/bge-reranker-v2-m3 for reranking, but routing
must use LOLM benchmark results rather than model reputation.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from lolm.capability_router import TaskKind, TaskProfile


class GroundingMode(str, Enum):
    DIRECT = "direct"
    RETRIEVAL_REQUIRED = "retrieval_required"
    CURRENT_REQUIRED = "current_required"
    SOURCE_CONSTRAINED = "source_constrained"


class ClaimKind(str, Enum):
    FACTUAL = "factual"
    TEMPORAL = "temporal"
    INFERENCE = "inference"
    OPINION = "opinion"
    INSTRUCTION = "instruction"


@dataclass(frozen=True)
class EvidencePassage:
    source_id: str
    text: str
    title: str = ""
    url: str = ""
    publisher: str = ""
    published_at: Optional[datetime] = None
    retrieved_at: Optional[datetime] = None
    authority: float = 0.5
    metadata: Mapping[str, object] = field(default_factory=dict)

    def normalized_published_at(self) -> Optional[datetime]:
        value = self.published_at
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def normalized_retrieved_at(self) -> Optional[datetime]:
        value = self.retrieved_at
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    text: str
    kind: ClaimKind = ClaimKind.FACTUAL
    source_ids: Tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    hedged: bool = False


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    claims: Tuple[ClaimRecord, ...]
    abstained: bool = False
    abstention_reason: str = ""


@dataclass(frozen=True)
class GroundingPolicy:
    mode: GroundingMode
    require_claim_ledger: bool
    require_citations: bool
    require_fresh_sources: bool
    max_source_age_days: Optional[int]
    minimum_coverage: float
    allow_uncited_opinion: bool = True


@dataclass(frozen=True)
class ClaimAssessment:
    claim_id: str
    supported: bool
    cited_sources_exist: bool
    fresh_enough: bool
    support_score: float
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class GroundingReport:
    valid: bool
    coverage: float
    unsupported_claim_rate: float
    citation_entailment_rate: float
    missing_source_ids: Tuple[str, ...]
    assessments: Tuple[ClaimAssessment, ...]
    errors: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "coverage": self.coverage,
            "unsupported_claim_rate": self.unsupported_claim_rate,
            "citation_entailment_rate": self.citation_entailment_rate,
            "missing_source_ids": list(self.missing_source_ids),
            "errors": list(self.errors),
            "assessments": [
                {
                    "claim_id": item.claim_id,
                    "supported": item.supported,
                    "cited_sources_exist": item.cited_sources_exist,
                    "fresh_enough": item.fresh_enough,
                    "support_score": round(item.support_score, 6),
                    "reasons": list(item.reasons),
                }
                for item in self.assessments
            ],
        }


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*")
_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
    "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "of",
    "on", "or", "she", "that", "the", "their", "them", "they", "this", "to",
    "was", "were", "will", "with", "you", "your",
})


def _tokens(text: str) -> List[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if token.lower() not in _STOP and len(token) > 1
    ]


def grounding_policy(
    profile: TaskProfile,
    *,
    supplied_sources: bool = False,
    source_constrained: bool = False,
) -> GroundingPolicy:
    """Derive the evidence contract for one answer."""
    if source_constrained:
        return GroundingPolicy(
            GroundingMode.SOURCE_CONSTRAINED,
            require_claim_ledger=True,
            require_citations=True,
            require_fresh_sources=profile.requires_current_information,
            max_source_age_days=7 if profile.requires_current_information else None,
            minimum_coverage=1.0,
        )
    if profile.requires_current_information or profile.kind == TaskKind.CURRENT_QA:
        return GroundingPolicy(
            GroundingMode.CURRENT_REQUIRED,
            require_claim_ledger=True,
            require_citations=True,
            require_fresh_sources=True,
            max_source_age_days=7,
            minimum_coverage=1.0,
        )
    if supplied_sources or profile.requires_retrieval or profile.kind == TaskKind.RESEARCH:
        return GroundingPolicy(
            GroundingMode.RETRIEVAL_REQUIRED,
            require_claim_ledger=True,
            require_citations=True,
            require_fresh_sources=False,
            max_source_age_days=None,
            minimum_coverage=0.95,
        )
    return GroundingPolicy(
        GroundingMode.DIRECT,
        require_claim_ledger=False,
        require_citations=False,
        require_fresh_sources=False,
        max_source_age_days=None,
        minimum_coverage=0.0,
    )


def _bm25_scores(query: str, passages: Sequence[EvidencePassage]) -> Dict[str, float]:
    """Small deterministic BM25 implementation for lexical retrieval."""
    q = _tokens(query)
    if not q or not passages:
        return {passage.source_id: 0.0 for passage in passages}
    docs = [_tokens(f"{passage.title} {passage.text}") for passage in passages]
    avg_len = sum(len(doc) for doc in docs) / max(len(docs), 1)
    document_frequency: Counter[str] = Counter()
    for doc in docs:
        document_frequency.update(set(doc))
    n_docs = len(docs)
    k1 = 1.5
    b = 0.75
    output: Dict[str, float] = {}
    for passage, doc in zip(passages, docs):
        frequencies = Counter(doc)
        score = 0.0
        for token in q:
            df = document_frequency.get(token, 0)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            tf = frequencies.get(token, 0)
            denom = tf + k1 * (1.0 - b + b * len(doc) / max(avg_len, 1.0))
            if denom:
                score += idf * ((tf * (k1 + 1.0)) / denom)
        output[passage.source_id] = score
    return output


def _normalize_scores(values: Mapping[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    finite = {key: float(value) for key, value in values.items() if math.isfinite(float(value))}
    if not finite:
        return {key: 0.0 for key in values}
    lo = min(finite.values())
    hi = max(finite.values())
    if abs(hi - lo) < 1e-12:
        return {key: (1.0 if value > 0 else 0.0) for key, value in finite.items()}
    return {key: (value - lo) / (hi - lo) for key, value in finite.items()}


def rank_evidence(
    query: str,
    passages: Sequence[EvidencePassage],
    *,
    dense_scores: Optional[Mapping[str, float]] = None,
    reranker_scores: Optional[Mapping[str, float]] = None,
    now: Optional[datetime] = None,
    current_required: bool = False,
    limit: int = 8,
) -> List[Tuple[EvidencePassage, float, Mapping[str, float]]]:
    """Hybrid lexical/dense/reranker ranking with source quality signals.

    `dense_scores` and `reranker_scores` are keyed by `source_id`. They can be
    produced by any backend, allowing Hugging Face models to be benchmarked and
    swapped without changing the evidence contract.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    lexical = _normalize_scores(_bm25_scores(query, passages))
    dense = _normalize_scores(dense_scores or {})
    reranked = _normalize_scores(reranker_scores or {})
    rows: List[Tuple[EvidencePassage, float, Mapping[str, float]]] = []
    for passage in passages:
        sid = passage.source_id
        lexical_score = lexical.get(sid, 0.0)
        dense_score = dense.get(sid, 0.0)
        reranker_score = reranked.get(sid, 0.0)
        authority = min(max(float(passage.authority), 0.0), 1.0)
        freshness = 0.5
        published = passage.normalized_published_at()
        retrieved = passage.normalized_retrieved_at()
        timestamp = published or retrieved
        if timestamp is not None:
            age_days = max((now_utc - timestamp).total_seconds() / 86400.0, 0.0)
            freshness = math.exp(-age_days / (7.0 if current_required else 365.0))
        elif current_required:
            freshness = 0.0
        # Reranker is strongest when available. Lexical remains present to avoid
        # dense-only semantic drift, especially around exact identifiers.
        score = (
            0.30 * lexical_score
            + 0.25 * dense_score
            + 0.30 * reranker_score
            + 0.10 * authority
            + 0.05 * freshness
        )
        rows.append((
            passage,
            score,
            {
                "lexical": lexical_score,
                "dense": dense_score,
                "reranker": reranker_score,
                "authority": authority,
                "freshness": freshness,
            },
        ))
    rows.sort(key=lambda row: (row[1], row[0].source_id), reverse=True)
    return rows[: max(int(limit), 0)]


def lexical_support_score(claim: str, passages: Sequence[EvidencePassage]) -> float:
    """Conservative deterministic support proxy.

    This is not semantic entailment. Production should inject an independently
    benchmarked NLI/reranker verifier. The lexical proxy exists so unsupported
    claims fail closed when the stronger verifier is unavailable.
    """
    claim_tokens = set(_tokens(claim))
    if not claim_tokens:
        return 1.0
    evidence_tokens: set[str] = set()
    for passage in passages:
        evidence_tokens.update(_tokens(passage.text))
        evidence_tokens.update(_tokens(passage.title))
    if not evidence_tokens:
        return 0.0
    return len(claim_tokens & evidence_tokens) / len(claim_tokens)


def validate_grounded_answer(
    answer: GroundedAnswer,
    passages: Sequence[EvidencePassage],
    policy: GroundingPolicy,
    *,
    support_fn: Optional[Callable[[str, Sequence[EvidencePassage]], float]] = None,
    support_threshold: float = 0.55,
    now: Optional[datetime] = None,
) -> GroundingReport:
    """Validate claim-level evidence and freshness.

    A valid abstention is allowed when evidence is missing. A non-abstaining
    source-constrained/current answer fails when any factual claim lacks support.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    source_map = {passage.source_id: passage for passage in passages}
    assess = support_fn or lexical_support_score
    assessments: List[ClaimAssessment] = []
    missing_ids: set[str] = set()
    errors: List[str] = []

    relevant_claims = [
        claim for claim in answer.claims
        if claim.kind not in {ClaimKind.OPINION, ClaimKind.INSTRUCTION}
    ]
    if answer.abstained:
        if not answer.abstention_reason.strip():
            errors.append("abstention_reason_missing")
        # An abstention must not carry affirmative factual claims.
        if relevant_claims:
            errors.append("abstention_contains_factual_claims")
        return GroundingReport(
            valid=not errors,
            coverage=1.0 if not relevant_claims else 0.0,
            unsupported_claim_rate=0.0 if not relevant_claims else 1.0,
            citation_entailment_rate=1.0 if not relevant_claims else 0.0,
            missing_source_ids=tuple(),
            assessments=tuple(),
            errors=tuple(errors),
        )

    if policy.require_claim_ledger and not answer.claims:
        errors.append("claim_ledger_missing")

    supported_count = 0
    cited_count = 0
    for claim in relevant_claims:
        reasons: List[str] = []
        cited = [source_map[sid] for sid in claim.source_ids if sid in source_map]
        missing = [sid for sid in claim.source_ids if sid not in source_map]
        missing_ids.update(missing)
        cited_sources_exist = not missing and bool(cited)
        if policy.require_citations and not claim.source_ids:
            reasons.append("citation_missing")
        if missing:
            reasons.append("citation_source_unknown")
        if cited:
            cited_count += 1

        fresh_enough = True
        if policy.require_fresh_sources:
            fresh_enough = False
            max_age = policy.max_source_age_days
            for passage in cited:
                timestamp = passage.normalized_published_at() or passage.normalized_retrieved_at()
                if timestamp is None:
                    continue
                age_days = max((now_utc - timestamp).total_seconds() / 86400.0, 0.0)
                if max_age is None or age_days <= max_age:
                    fresh_enough = True
                    break
            if not fresh_enough:
                reasons.append("fresh_source_missing")

        support_score = float(assess(claim.text, cited)) if cited else 0.0
        support_score = min(max(support_score, 0.0), 1.0)
        supported = (
            (not policy.require_citations or cited_sources_exist)
            and fresh_enough
            and support_score >= support_threshold
        )
        if not supported and support_score < support_threshold:
            reasons.append("evidence_does_not_support_claim")
        if supported:
            supported_count += 1
        assessments.append(ClaimAssessment(
            claim.claim_id,
            supported=supported,
            cited_sources_exist=cited_sources_exist,
            fresh_enough=fresh_enough,
            support_score=support_score,
            reasons=tuple(reasons),
        ))

    denominator = len(relevant_claims)
    coverage = cited_count / denominator if denominator else 1.0
    entailment_rate = supported_count / cited_count if cited_count else (1.0 if denominator == 0 else 0.0)
    unsupported_rate = (denominator - supported_count) / denominator if denominator else 0.0

    if coverage + 1e-12 < policy.minimum_coverage:
        errors.append("citation_coverage_below_threshold")
    if unsupported_rate > 0.0 and policy.mode in {
        GroundingMode.SOURCE_CONSTRAINED,
        GroundingMode.CURRENT_REQUIRED,
    }:
        errors.append("unsupported_factual_claims")
    if missing_ids:
        errors.append("unknown_citation_sources")

    return GroundingReport(
        valid=not errors,
        coverage=coverage,
        unsupported_claim_rate=unsupported_rate,
        citation_entailment_rate=entailment_rate,
        missing_source_ids=tuple(sorted(missing_ids)),
        assessments=tuple(assessments),
        errors=tuple(errors),
    )


def answer_from_dict(payload: Mapping[str, object]) -> GroundedAnswer:
    """Parse the strict structured answer schema emitted by a writer model."""
    claims: List[ClaimRecord] = []
    raw_claims = payload.get("claims") or []
    if not isinstance(raw_claims, list):
        raise ValueError("claims must be a list")
    for index, item in enumerate(raw_claims):
        if not isinstance(item, Mapping):
            raise ValueError(f"claim {index} must be an object")
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError(f"claim {index} text is required")
        raw_kind = str(item.get("kind") or ClaimKind.FACTUAL.value)
        try:
            kind = ClaimKind(raw_kind)
        except ValueError as exc:
            raise ValueError(f"claim {index} has invalid kind {raw_kind!r}") from exc
        source_ids_raw = item.get("source_ids") or []
        if not isinstance(source_ids_raw, list) or not all(isinstance(value, str) for value in source_ids_raw):
            raise ValueError(f"claim {index} source_ids must be a string list")
        claims.append(ClaimRecord(
            claim_id=str(item.get("claim_id") or f"c{index + 1}"),
            text=text,
            kind=kind,
            source_ids=tuple(source_ids_raw),
            confidence=float(item.get("confidence") or 0.0),
            hedged=bool(item.get("hedged")),
        ))
    return GroundedAnswer(
        text=str(payload.get("answer") or payload.get("text") or ""),
        claims=tuple(claims),
        abstained=bool(payload.get("abstained")),
        abstention_reason=str(payload.get("abstention_reason") or ""),
    )
