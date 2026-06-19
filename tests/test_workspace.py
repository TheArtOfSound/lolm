# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the persistent agent-workspace store."""

from local_ui.workspace_store import WorkspaceStore


def test_conversation_lifecycle(tmp_path):
    s = WorkspaceStore(tmp_path)
    c = s.create_conversation(owner="u1")
    cid = c["id"]
    assert c["title"] == "New conversation"

    # first user message auto-titles the conversation
    s.append_message(cid, "user", "Fix the broken verify page", model_used="")
    s.append_message(cid, "assistant", "Here is the fix...", model_used="llama-70b",
                     receipt_id="rcpt_1", verdict="shipped")
    full = s.get_conversation(cid)
    assert full["title"] == "Fix the broken verify page"
    assert len(full["messages"]) == 2
    assert full["last_model_used"] == "llama-70b"
    assert full["last_verdict"] == "shipped"
    assert full["messages"][1]["receipt_id"] == "rcpt_1"


def test_owner_scoping(tmp_path):
    s = WorkspaceStore(tmp_path)
    s.create_conversation(owner="alice", title="a")
    s.create_conversation(owner="bob", title="b")
    assert {c["title"] for c in s.list_conversations(owner="alice")} == {"a"}
    assert {c["title"] for c in s.list_conversations(owner="bob")} == {"b"}
    assert len(s.list_conversations()) == 2  # no owner filter = all


def test_rename_archive_search(tmp_path):
    s = WorkspaceStore(tmp_path)
    c = s.create_conversation(owner="u")
    s.append_message(c["id"], "user", "build a rocket")
    s.rename_conversation(c["id"], "Rocket project")
    assert s.get_conversation(c["id"])["title"] == "Rocket project"
    # search matches title or message content
    assert s.list_conversations(owner="u", query="rocket")
    assert not s.list_conversations(owner="u", query="banana")
    # archive hides it by default
    s.set_archived(c["id"], True)
    assert not s.list_conversations(owner="u")
    assert s.list_conversations(owner="u", include_archived=True)


def test_projects(tmp_path):
    s = WorkspaceStore(tmp_path)
    p = s.create_project("lolm", repo_url="https://github.com/TheArtOfSound/lolm",
                         package_manager="npm")
    assert p["name"] == "lolm"
    rows = s.list_projects()
    assert rows[0]["repo_url"].endswith("/lolm")


def test_missing_conversation(tmp_path):
    s = WorkspaceStore(tmp_path)
    assert s.get_conversation("conv_nope") is None
    assert s.append_message("conv_nope", "user", "x") is None
    assert s.rename_conversation("conv_nope", "y") is None
