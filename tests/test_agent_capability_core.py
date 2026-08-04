from datetime import datetime, timezone

from lolm.agent_capability_core import AgentCapabilityCore
from lolm.capability_router import AgentRole, ModelCapability, TaskKind
from lolm.grounded_qa import ClaimRecord, EvidencePassage, GroundedAnswer
from lolm.repo_context import SourceDocument


def model(model_id, provider, **overrides):
    values = dict(
        context_tokens=100_000,
        reasoning=0.8,
        coding=0.8,
        repo_editing=0.8,
        tool_use=0.8,
        structured_output=0.8,
        factuality=0.8,
        verification=0.8,
        latency=0.5,
        cost=0.5,
    )
    values.update(overrides)
    return ModelCapability(model_id, provider, **values)


def test_prepare_request_combines_profile_route_and_grounding():
    core = AgentCapabilityCore(registry=[
        model("writer", "p1", coding=0.95, tool_use=0.95),
        model("checker", "p2", verification=0.95),
    ])
    decision = core.prepare_request(
        "Research the latest release and fix the existing repository",
        has_repository=True,
        supplied_sources=True,
    )
    assert decision.profile.kind == TaskKind.REPO_EDIT
    assert decision.profile.requires_retrieval is True
    assert decision.route.model_for(AgentRole.EXECUTOR) is not None
    assert decision.grounding.require_citations is True
    events = [e["event"] for e in core.telemetry.events]
    assert "request_profiled" in events
    assert "shadow_router_observation" in events
    assert decision.shadow is not None
    assert decision.to_dict()["adaptive_routing_applied"] is False


def test_prepare_command_blocks_snake_failure_before_shell():
    core = AgentCapabilityCore()
    decision = core.prepare_command(
        "node --check <(sed -n '/<script>/,/<\\/script>/p' index.html)",
        artifact_path="index.html",
        primary_language="html",
        known_files=["index.html"],
    )
    assert decision.allowed is False
    assert decision.preflight.primary_failure.value == "shell_dialect"
    assert decision.verifier_candidates[0].verifier == "html.render"
    assert core.telemetry.events[-1]["data"]["accepted"] is False


def test_prepare_repository_selects_relevant_symbol():
    core = AgentCapabilityCore()
    decision = core.prepare_repository(
        "Fix verify_receipt hash validation",
        [
            SourceDocument("receipt.py", "def verify_receipt(value):\n    return bool(value)\n"),
            SourceDocument("colors.py", "COLORS = ['red']\n"),
        ],
        token_budget=300,
    )
    assert decision.context.items[0].path == "receipt.py"
    assert "verify_receipt" in decision.context.items[0].excerpt
    assert core.telemetry.events[-1]["event"] == "repository_context_selected"


def test_verify_answer_records_grounding_outcome():
    core = AgentCapabilityCore()
    request = core.prepare_request(
        "According to these sources, what Python version is required?",
        supplied_sources=True,
        source_constrained=True,
    )
    answer = GroundedAnswer(
        "Python 3.12 is required.",
        claims=(ClaimRecord("c1", "Python 3.12 is required", source_ids=("S1",)),),
    )
    report = core.verify_answer(
        answer,
        [EvidencePassage("S1", "The application requires Python 3.12.")],
        request.grounding,
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert report.valid is True
    assert core.telemetry.events[-1]["event"] == "answer_grounding_verified"
    assert core.telemetry.events[-1]["data"]["unsupported_claim_rate"] == 0.0


def test_request_decision_is_serializable():
    core = AgentCapabilityCore(registry=[model("one", "p1")])
    payload = core.prepare_request("Write a Python function").to_dict()
    assert payload["profile"]["language"] == "python"
    assert payload["route"]["assignments"]
    assert payload["grounding"]["mode"] == "direct"
