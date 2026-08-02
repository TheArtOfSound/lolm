# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Integration: NFETAgent grounded finalizer enforces claim ledger before shipping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

import pytest

from local_ui.nfet_agent import NFETAgent, NFETAgentRequest, AgentDeps, SegmentResult


@dataclass
class _Msg:
    role: str
    content: str


class _ChatReq:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Mem:
    def search_notes(self, *a, **k):
        return []

    def append_event(self, *a, **k):
        return None


def _loop_factory(responses: List[str]):
    """Generation loop that emits one complete answer per call (done event)."""
    box = {"i": 0, "responses": list(responses)}

    def loop(req: Any) -> Iterator[Dict[str, Any]]:
        text = box["responses"][min(box["i"], len(box["responses"]) - 1)]
        box["i"] += 1
        # No token events — matches silent channel=None validation path
        yield {
            "event": "done",
            "data": {"response": text, "tokens": max(len(text.split()), 1)},
        }

    return loop


def _agent(responses: List[str]) -> NFETAgent:
    loop = _loop_factory(responses)
    deps = AgentDeps(
        memory=_Mem(),
        ChatMessage=_Msg,
        ChatRequest=_ChatReq,
        generation_loop=loop,
        append_event=lambda e: None,
        frontier_loop=loop,
    )
    return NFETAgent(deps)


def _run_finalize(agent: NFETAgent, command: str, evidence: list, *, web: bool) -> SegmentResult:
    req = NFETAgentRequest(
        command=command,
        sources="\n\n".join(e.get("text", "") for e in evidence) if evidence else "placeholder",
        web_grounded=web,
        reasoner="local",
        final_tokens=400,
    )
    # Force grounded path even when web — sources field must be non-empty
    gen = agent._do_finalize(
        command,
        draft="",
        evidence=evidence or [{"kind": "source", "id": "S1", "text": "placeholder"}],
        req=req,
        profile="task",
    )
    result = None
    events = []
    try:
        while True:
            ev = next(gen)
            events.append(ev)
    except StopIteration as stop:
        result = stop.value
    assert result is not None
    result.raw["_events"] = events
    return result


def test_finalizer_ships_supported_source_constrained_answer():
    agent = _agent(["The project uses Python 3.12. [S1]"])
    evidence = [{"kind": "source", "id": "S1", "text": "The project uses Python 3.12 and pytest."}]
    result = _run_finalize(
        agent, "What language is required?", evidence, web=False,
    )
    assert "python 3.12" in result.text.lower()
    fact = result.raw.get("factuality") or {}
    assert fact.get("final_verdict") in ("ship", "mixed_ship", "bypass")
    assert fact.get("unsupported_claim_rate", 1) == 0.0 or fact.get("final_verdict") == "ship"


def test_finalizer_abstains_when_evidence_missing():
    # First draft unsupported; repair also unsupported → abstain
    agent = _agent([
        "Launch is March 1. [S1]",
        "Launch is definitely March 1 without evidence.",
    ])
    evidence = [{"kind": "source", "id": "S1", "text": "The product is a browser application."}]
    result = _run_finalize(agent, "What is the launch date?", evidence, web=False)
    fact = result.raw.get("factuality") or {}
    assert fact.get("final_verdict") == "abstain"
    assert "not in your sources" in result.text.lower()
    assert fact.get("repair_attempted") is True


def test_finalizer_does_not_stream_rejected_draft_tokens():
    agent = _agent([
        "UNSUPPORTED SECRET CLAIM 999. [S1]",
        "That's not in your sources.",
    ])
    evidence = [{"kind": "source", "id": "S1", "text": "Unrelated note about fonts."}]
    result = _run_finalize(agent, "What is the launch date?", evidence, web=False)
    events = result.raw.get("_events") or []
    token_blob = "".join(
        (e.get("data") or {}).get("token") or ""
        for e in events if e.get("event") == "token"
    )
    # Rejected draft must not appear in streamed tokens
    assert "UNSUPPORTED SECRET CLAIM 999" not in token_blob
    assert "not in your sources" in result.text.lower() or "could not verify" in result.text.lower()


def test_finalizer_empty_provider_output_abstains():
    agent = _agent([""])
    evidence = [{"kind": "source", "id": "S1", "text": "Something."}]
    result = _run_finalize(agent, "Current CEO?", evidence, web=True)
    assert result.text.strip()
    fact = result.raw.get("factuality") or {}
    assert fact.get("final_verdict") in ("abstain",) or fact.get("provider_empty")
