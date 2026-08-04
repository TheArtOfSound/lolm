from datetime import datetime, timedelta, timezone

import pytest

from lolm.capability_router import TaskKind, TaskProfile
from lolm.grounded_qa import (
    ClaimKind,
    ClaimRecord,
    EvidencePassage,
    GroundedAnswer,
    GroundingMode,
    answer_from_dict,
    grounding_policy,
    rank_evidence,
    validate_grounded_answer,
)


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def passage(source_id, text, **kwargs):
    return EvidencePassage(source_id=source_id, text=text, **kwargs)


def test_current_question_requires_fresh_cited_claims():
    profile = TaskProfile(
        kind=TaskKind.CURRENT_QA,
        requires_current_information=True,
        requires_retrieval=True,
    )
    policy = grounding_policy(profile)
    assert policy.mode == GroundingMode.CURRENT_REQUIRED
    assert policy.require_citations is True
    assert policy.require_fresh_sources is True


def test_source_constrained_policy_requires_full_coverage():
    profile = TaskProfile(kind=TaskKind.FACTUAL_QA)
    policy = grounding_policy(profile, supplied_sources=True, source_constrained=True)
    assert policy.mode == GroundingMode.SOURCE_CONSTRAINED
    assert policy.minimum_coverage == 1.0


def test_valid_source_constrained_answer_passes():
    policy = grounding_policy(
        TaskProfile(kind=TaskKind.FACTUAL_QA),
        supplied_sources=True,
        source_constrained=True,
    )
    sources = [passage("S1", "The project uses Python 3.12 and pytest for tests.")]
    answer = GroundedAnswer(
        "The project uses Python 3.12. [S1]",
        claims=(ClaimRecord("c1", "The project uses Python 3.12", source_ids=("S1",)),),
    )
    report = validate_grounded_answer(answer, sources, policy)
    assert report.valid is True
    assert report.coverage == 1.0
    assert report.unsupported_claim_rate == 0.0


def test_unknown_source_id_fails_closed():
    policy = grounding_policy(
        TaskProfile(kind=TaskKind.FACTUAL_QA),
        supplied_sources=True,
        source_constrained=True,
    )
    answer = GroundedAnswer(
        "A claim",
        claims=(ClaimRecord("c1", "A claim", source_ids=("S404",)),),
    )
    report = validate_grounded_answer(answer, [], policy)
    assert report.valid is False
    assert report.missing_source_ids == ("S404",)
    assert "unknown_citation_sources" in report.errors


def test_unsupported_claim_fails_even_when_a_source_is_cited():
    policy = grounding_policy(
        TaskProfile(kind=TaskKind.FACTUAL_QA),
        supplied_sources=True,
        source_constrained=True,
    )
    sources = [passage("S1", "The release supports Python 3.12.")]
    answer = GroundedAnswer(
        "The release won a design award.",
        claims=(ClaimRecord("c1", "The release won a design award", source_ids=("S1",)),),
    )
    report = validate_grounded_answer(answer, sources, policy)
    assert report.valid is False
    assert report.unsupported_claim_rate == 1.0
    assert "unsupported_factual_claims" in report.errors


def test_current_claim_rejects_stale_source():
    policy = grounding_policy(TaskProfile(
        kind=TaskKind.CURRENT_QA,
        requires_current_information=True,
        requires_retrieval=True,
    ))
    sources = [passage(
        "S1",
        "The current version is 3.0.",
        published_at=NOW - timedelta(days=30),
    )]
    answer = GroundedAnswer(
        "The current version is 3.0.",
        claims=(ClaimRecord(
            "c1", "The current version is 3.0", kind=ClaimKind.TEMPORAL, source_ids=("S1",)
        ),),
    )
    report = validate_grounded_answer(answer, sources, policy, now=NOW)
    assert report.valid is False
    assert report.assessments[0].fresh_enough is False
    assert "fresh_source_missing" in report.assessments[0].reasons


def test_current_claim_accepts_recent_retrieval_timestamp():
    policy = grounding_policy(TaskProfile(
        kind=TaskKind.CURRENT_QA,
        requires_current_information=True,
        requires_retrieval=True,
    ))
    sources = [passage(
        "S1",
        "The current version is 3.0.",
        retrieved_at=NOW - timedelta(hours=2),
    )]
    answer = GroundedAnswer(
        "The current version is 3.0.",
        claims=(ClaimRecord(
            "c1", "The current version is 3.0", kind=ClaimKind.TEMPORAL, source_ids=("S1",)
        ),),
    )
    report = validate_grounded_answer(answer, sources, policy, now=NOW)
    assert report.valid is True


def test_honest_abstention_passes_when_reason_is_present():
    policy = grounding_policy(
        TaskProfile(kind=TaskKind.FACTUAL_QA),
        supplied_sources=True,
        source_constrained=True,
    )
    answer = GroundedAnswer(
        "The supplied sources do not answer that question.",
        claims=(),
        abstained=True,
        abstention_reason="No passage contains the requested information.",
    )
    report = validate_grounded_answer(answer, [], policy)
    assert report.valid is True


def test_abstention_cannot_hide_affirmative_claims():
    policy = grounding_policy(
        TaskProfile(kind=TaskKind.FACTUAL_QA),
        supplied_sources=True,
        source_constrained=True,
    )
    answer = GroundedAnswer(
        "I cannot answer, but it is probably version 4.",
        claims=(ClaimRecord("c1", "It is version 4"),),
        abstained=True,
        abstention_reason="Evidence missing.",
    )
    report = validate_grounded_answer(answer, [], policy)
    assert report.valid is False
    assert "abstention_contains_factual_claims" in report.errors


def test_opinion_does_not_reduce_factual_coverage():
    policy = grounding_policy(
        TaskProfile(kind=TaskKind.RESEARCH, requires_retrieval=True),
        supplied_sources=True,
    )
    sources = [passage("S1", "Model A passed 90 percent of the benchmark.")]
    answer = GroundedAnswer(
        "Model A passed 90 percent. I think that is impressive.",
        claims=(
            ClaimRecord("c1", "Model A passed 90 percent of the benchmark", source_ids=("S1",)),
            ClaimRecord("c2", "That result is impressive", kind=ClaimKind.OPINION),
        ),
    )
    report = validate_grounded_answer(answer, sources, policy)
    assert report.valid is True
    assert report.coverage == 1.0


def test_hybrid_retrieval_preserves_exact_identifier_match():
    passages = [
        passage("exact", "Commit ecc9a7a fixes HTML routing.", authority=0.7),
        passage("semantic", "A general article about software agents.", authority=1.0),
    ]
    ranked = rank_evidence(
        "What changed in ecc9a7a?",
        passages,
        dense_scores={"exact": 0.2, "semantic": 1.0},
        reranker_scores={"exact": 1.0, "semantic": 0.3},
        now=NOW,
    )
    assert ranked[0][0].source_id == "exact"
    assert ranked[0][2]["lexical"] > ranked[1][2]["lexical"]


def test_current_retrieval_penalizes_undated_source():
    passages = [
        passage(
            "recent",
            "The current release is 4.0.",
            published_at=NOW - timedelta(days=1),
        ),
        passage("undated", "The current release is 4.0."),
    ]
    ranked = rank_evidence(
        "current release",
        passages,
        dense_scores={"recent": 0.5, "undated": 0.5},
        reranker_scores={"recent": 0.5, "undated": 0.5},
        now=NOW,
        current_required=True,
    )
    assert ranked[0][0].source_id == "recent"
    assert ranked[0][2]["freshness"] > ranked[1][2]["freshness"]


def test_answer_schema_parser_is_strict():
    answer = answer_from_dict({
        "answer": "Python 3.12 is required.",
        "claims": [{
            "claim_id": "c1",
            "text": "Python 3.12 is required",
            "kind": "factual",
            "source_ids": ["S1"],
            "confidence": 0.9,
        }],
    })
    assert answer.claims[0].source_ids == ("S1",)
    with pytest.raises(ValueError):
        answer_from_dict({"claims": [{"text": "x", "source_ids": "S1"}]})
