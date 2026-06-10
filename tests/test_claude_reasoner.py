from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ui.claude_reasoner import ClaudeReasonerLoop, _split_messages
from local_ui.memory_store import MemoryStore
from local_ui.nfet_agent import AgentDeps, NFETAgent, NFETAgentRequest


class Msg:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


class Req:
    def __init__(self, messages, max_new_tokens=96, temperature=0.35, top_p=0.9,
                 use_graft=True, ablation_mode="full"):
        self.messages = messages
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.use_graft = use_graft
        self.ablation_mode = ablation_mode


class FakeAnthropicClient:
    def __init__(self, text="Claude says hello.", fail=False):
        self.text = text
        self.fail = fail
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("api exploded")
        block = SimpleNamespace(type="text", text=self.text)
        usage = SimpleNamespace(input_tokens=42, output_tokens=7)
        return SimpleNamespace(content=[block], usage=usage)


def empty_state():
    return SimpleNamespace(backbone=None, graft=None)


def test_split_messages_maps_roles():
    system, turns = _split_messages([
        Msg("system", "You are the drafting engine."),
        Msg("system", "Extra context."),
        Msg("user", "Write a thing."),
    ])
    assert "drafting engine" in system and "Extra context." in system
    assert turns == [{"role": "user", "content": "Write a thing."}]


def test_claude_loop_emits_protocol_events_without_local_model():
    client = FakeAnthropicClient(text="The latent order holds.")
    loop = ClaudeReasonerLoop(empty_state, client=client)
    events = list(loop(Req([Msg("system", "sys"), Msg("user", "go")])))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert "token" in kinds
    done = events[-1]["data"]
    assert done["response"] == "The latent order holds."
    assert done["reasoner"] == "claude"
    assert done["claude_usage"]["output_tokens"] == 7
    # text reassembles from token events
    text = "".join(e["data"]["token"] for e in events if e["event"] == "token").strip()
    assert text == "The latent order holds."
    # no sampling params were sent (removed on Opus 4.7+)
    sent = client.calls[0]
    assert "temperature" not in sent and "top_p" not in sent and "top_k" not in sent
    assert sent["system"] == "sys"


def test_claude_loop_yields_error_event_on_failure():
    loop = ClaudeReasonerLoop(empty_state, client=FakeAnthropicClient(fail=True))
    events = list(loop(Req([Msg("user", "go")])))
    assert events[0]["event"] == "error"
    assert "claude reasoner failed" in events[0]["data"]["error"]


def test_agent_routes_to_frontier_loop(tmp_path):
    client = FakeAnthropicClient(text="Result: frontier answer with full evidence and verification.")
    frontier = ClaudeReasonerLoop(empty_state, client=client)
    events = []
    memory = MemoryStore(tmp_path / "data")
    deps = AgentDeps(
        memory=memory, ChatMessage=Msg, ChatRequest=Req,
        generation_loop=lambda req: (_ for _ in ()).throw(AssertionError("local loop must not run")),
        append_event=events.append,
        frontier_loop=frontier,
    )
    agent = NFETAgent(deps)
    out = agent.run(NFETAgentRequest(command="explain lolm", reasoner="claude", max_segments=2))
    assert out["reasoner"] == "claude"
    assert out["result"]["response"].startswith("Result: frontier answer")
    # without local telemetry the policy stays in calibration -> continue
    assert all(t["decision"]["label"] == "continue" for t in out["timeline"])
    assert events[0]["reasoner"] == "claude"


def test_agent_errors_cleanly_when_frontier_missing(tmp_path):
    deps = AgentDeps(
        memory=MemoryStore(tmp_path / "data"), ChatMessage=Msg, ChatRequest=Req,
        generation_loop=lambda req: iter([]), append_event=lambda e: None,
    )
    agent = NFETAgent(deps)
    with pytest.raises(RuntimeError, match="no frontier loop"):
        agent.run(NFETAgentRequest(command="x", reasoner="claude"))
