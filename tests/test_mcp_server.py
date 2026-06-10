from __future__ import annotations

import os

import pytest

# Route workspace data into a temp dir BEFORE importing the server module.
os.environ.setdefault("LOCAL_UI_DATA_DIR", "/tmp/lolm-mcp-test-data")

from local_ui import mcp_server  # noqa: E402


def test_all_tools_registered():
    names = {t.__name__ for t in mcp_server.TOOLS}
    assert {"workspace_status", "load_local_model", "lolm_chat", "nfet_agent_run",
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
