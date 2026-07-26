from __future__ import annotations

import hashlib
import os

import pytest

# Route workspace data into a temp dir BEFORE importing the server module.
os.environ.setdefault("LOCAL_UI_DATA_DIR", "/tmp/lolm-mcp-test-data")

from local_ui import mcp_server  # noqa: E402


def test_all_tools_registered():
    names = {t.__name__ for t in mcp_server.TOOLS}
    assert {"workspace_status", "load_local_model", "lolm_chat", "nfet_agent_run",
            "nfet_monitor_text",
            "memory_search", "memory_add_note", "goals_add", "journal_write",
            "improvement_log_tail"} <= names
    registered = set()
    # FastMCP keeps registered tools in its tool manager
    import anyio

    async def collect():
        for tool in await mcp_server.mcp.list_tools():
            registered.add(tool.name)
    anyio.run(collect)
    assert {t.__name__ for t in mcp_server.TOOLS} <= registered


def test_memory_tools_round_trip():
    saved = mcp_server.memory_add_note("MCP test note about latent order", tag="test", importance=4)
    assert saved["saved"]
    hits = mcp_server.memory_search("latent order")
    assert any("latent order" in item["text"] for item in hits["items"])
    goal = mcp_server.goals_add("Test goal", why="because", priority=4)
    assert goal["saved"]
    assert any(g["title"] == "Test goal" for g in mcp_server.goals_list()["items"])
    mcp_server.journal_write("MCP journal entry")
    assert "MCP journal entry" in mcp_server.journal_read()["journal"]
    identity = mcp_server.identity_add_line("This workspace is under test.")
    assert identity["saved"]
    assert "under test" in mcp_server.identity_get()["identity"]


def test_status_and_log_tail_work_without_model():
    status = mcp_server.workspace_status()
    assert status["loaded"] is False
    tail = mcp_server.improvement_log_tail(limit=5)
    assert "items" in tail


def test_chat_without_model_raises_http_error():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        mcp_server.lolm_chat("hello")


def test_monitor_without_model_returns_load_instruction():
    result = mcp_server.nfet_monitor_text("A draft plan", reset=True)
    assert result["error"] == "LOLM model is not loaded"
    assert "load_local_model" in result["next"]


def test_monitor_replays_external_text(monkeypatch):
    monkeypatch.setattr(mcp_server.workspace.STATE, "backbone", object())
    monkeypatch.setattr(mcp_server.workspace.STATE, "graft", object())
    monkeypatch.setattr(mcp_server.workspace.STATE, "profile", "test-profile")
    monkeypatch.setattr(mcp_server.workspace.STATE, "head_trained", False)

    traces = [
        {
            "step": index + 1,
            "used_graft": True,
            "graft_entropy": 2.0 + index * 0.01,
            "hidden_drift": 0.1,
            "gate_mean": 0.5,
            "regime_entropy": 1.5,
            "control_logits": [0.0, 0.0, 0.0, 0.0, 0.0],
        }
        for index in range(16)
    ]
    monkeypatch.setattr(
        mcp_server,
        "telemetry_traces_from_text",
        lambda backbone, graft, text, max_tokens: traces,
    )

    result = mcp_server.nfet_monitor_text("A Codex-generated plan", reset=True)

    assert result["profile"] == "test-profile"
    assert result["observed_tokens"] == 16
    assert result["monitor_frames_seen"] == 16
    assert result["decision"]["label"] in {
        "continue", "retrieve", "verify", "branch", "finalize"
    }
    assert result["codex_action"]


def _monitor_traces(entropy=2.0, logits=None, count=16):
    logits = logits or [0.0, 0.0, 0.0, 0.0, 0.0]
    return [
        {
            "step": index + 1,
            "used_graft": True,
            "graft_entropy": entropy,
            "hidden_drift": 0.1,
            "gate_mean": 0.5,
            "regime_entropy": 1.5,
            "control_logits": list(logits),
        }
        for index in range(count)
    ]


def _arm_monitor(monkeypatch, traces, *, trained=True):
    monkeypatch.setattr(mcp_server.workspace.STATE, "backbone", object())
    monkeypatch.setattr(mcp_server.workspace.STATE, "graft", object())
    monkeypatch.setattr(mcp_server.workspace.STATE, "profile", "test-profile")
    monkeypatch.setattr(mcp_server.workspace.STATE, "head_trained", trained)
    monkeypatch.setattr(
        mcp_server,
        "telemetry_traces_from_text",
        lambda backbone, graft, text, max_tokens: traces,
    )


def test_monitor_aggregates_tail_instead_of_using_terminal_token():
    traces = _monitor_traces(logits=[5.0, 0.0, 0.0, 0.0, 0.0], count=15)
    traces += _monitor_traces(logits=[0.0, 100.0, 0.0, 0.0, 0.0], count=1)

    logits = mcp_server._aggregate_control_logits(traces)

    assert logits is not None
    assert logits[0] > logits[1]


def test_monitor_rejects_unsupported_retrieve(monkeypatch):
    _arm_monitor(monkeypatch, _monitor_traces(logits=[0.0, 8.0, 0.0, 0.0, 0.0]))
    monkeypatch.setattr(mcp_server.workspace, "append_improvement_event", lambda event: None)

    result = mcp_server.nfet_monitor_text(
        "A plan with no uncertainty spike", reset=True, checkpoint="plan",
    )

    assert result["decision"]["label"] == "continue"
    assert result["decision"]["source"] == "telemetry_guard"
    assert result["decision"]["head_probs"][1] > 0.99
    assert mcp_server._MONITOR_POLICY.last_action_at == -10_000


def test_monitor_keeps_supported_retrieve(monkeypatch):
    batches = iter([
        _monitor_traces(entropy=2.0),
        _monitor_traces(entropy=4.0, logits=[0.0, 8.0, 0.0, 0.0, 0.0]),
    ])
    _arm_monitor(monkeypatch, [])
    monkeypatch.setattr(
        mcp_server,
        "telemetry_traces_from_text",
        lambda backbone, graft, text, max_tokens: next(batches),
    )
    monkeypatch.setattr(mcp_server.workspace, "append_improvement_event", lambda event: None)
    mcp_server.nfet_monitor_text("baseline", reset=True, checkpoint="plan")

    result = mcp_server.nfet_monitor_text("uncertain work", checkpoint="work")

    assert result["decision"]["label"] == "retrieve"
    assert result["decision"]["source"] == "head"
    assert result["monitor_frames_seen"] == 32


def test_monitor_finalizes_only_explicit_verified_result(monkeypatch):
    _arm_monitor(monkeypatch, _monitor_traces(logits=[0.0, 8.0, 0.0, 0.0, 0.0]))
    monkeypatch.setattr(mcp_server.workspace, "append_improvement_event", lambda event: None)

    result = mcp_server.nfet_monitor_text(
        "Tests passed", reset=True, checkpoint="result", verified=True,
    )

    assert result["decision"]["label"] == "finalize"
    assert result["decision"]["source"] == "verified_result"


def test_monitor_persists_privacy_safe_receipt(monkeypatch):
    text = "Safe result summary, not hidden reasoning"
    events = []
    _arm_monitor(monkeypatch, _monitor_traces(), trained=False)
    monkeypatch.setattr(mcp_server.workspace, "append_improvement_event", events.append)

    result = mcp_server.nfet_monitor_text(text, reset=True, checkpoint="plan")

    assert result["receipt_id"] == events[0]["id"]
    assert events[0]["type"] == "monitor"
    assert events[0]["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert events[0]["text_chars"] == len(text)
    assert "text" not in events[0]


@pytest.mark.parametrize("checkpoint", ["", "draft", "finished"])
def test_monitor_rejects_unknown_checkpoint(checkpoint):
    result = mcp_server.nfet_monitor_text("text", checkpoint=checkpoint)
    assert "checkpoint must be one of" in result["error"]


def test_monitor_rejects_verified_non_result():
    result = mcp_server.nfet_monitor_text("text", checkpoint="work", verified=True)
    assert result["error"] == "verified=true is only valid for checkpoint=result"
