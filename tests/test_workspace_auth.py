# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Adversarial authentication and ownership tests for persistent workspace data."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from local_ui import api_keys
from local_ui.workspace_routes import register_workspace_routes
from local_ui.workspace_store import WorkspaceStore


def _client(tmp_path):
    api_keys.init(tmp_path / "keys")
    alice = api_keys.mint_api_key(tier="free", label="alice", ip="10.0.0.1")["api_key"]
    bob = api_keys.mint_api_key(tier="free", label="bob", ip="10.0.0.2")["api_key"]
    app = FastAPI()
    register_workspace_routes(app, WorkspaceStore(tmp_path / "workspace"))
    return TestClient(app), {
        "alice": {"X-LOLM-Api-Key": alice},
        "bob": {"X-LOLM-Api-Key": bob},
    }


def test_anonymous_persistent_workspace_is_denied(tmp_path):
    client, _ = _client(tmp_path)
    calls = [
        ("get", "/api/demo/workspace/memory", None),
        ("post", "/api/demo/workspace/memory", {"text": "secret"}),
        ("post", "/api/demo/workspace/memory/clear", None),
        ("post", "/api/demo/workspace/conversations", {"title": "secret"}),
        ("get", "/api/demo/workspace/conversations", None),
        ("post", "/api/demo/workspace/projects", {"name": "secret"}),
        ("get", "/api/demo/workspace/projects", None),
    ]
    for method, path, body in calls:
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 401, (method, path, response.status_code, response.text)


def test_memory_identity_comes_only_from_authenticated_principal(tmp_path):
    client, headers = _client(tmp_path)
    assert client.post(
        "/api/demo/workspace/memory",
        headers={**headers["alice"], "X-Workspace-Owner": "bob"},
        json={"text": "alice secret", "owner": "bob"},
    ).status_code == 200
    assert client.post(
        "/api/demo/workspace/memory",
        headers=headers["bob"],
        json={"text": "bob secret", "owner": "alice"},
    ).status_code == 200

    alice = client.get("/api/demo/workspace/memory", headers=headers["alice"]).json()["memories"]
    bob = client.get("/api/demo/workspace/memory", headers=headers["bob"]).json()["memories"]
    assert [m["text"] for m in alice] == ["alice secret"]
    assert [m["text"] for m in bob] == ["bob secret"]

    alice_id = alice[0]["id"]
    assert client.delete(
        f"/api/demo/workspace/memory/{alice_id}", headers=headers["bob"]
    ).json()["deleted"] is False
    assert client.post(
        "/api/demo/workspace/memory/clear", headers=headers["bob"]
    ).json()["cleared"] == 1
    assert len(client.get(
        "/api/demo/workspace/memory", headers=headers["alice"]
    ).json()["memories"]) == 1


def test_conversations_and_projects_enforce_object_ownership(tmp_path):
    client, headers = _client(tmp_path)
    conv = client.post(
        "/api/demo/workspace/conversations", headers=headers["alice"], json={"title": "alice"}
    ).json()
    project = client.post(
        "/api/demo/workspace/projects", headers=headers["alice"], json={"name": "alice project"}
    ).json()

    for method, path, body in [
        ("get", f"/api/demo/workspace/conversations/{conv['id']}", None),
        ("patch", f"/api/demo/workspace/conversations/{conv['id']}", {"title": "stolen"}),
        ("post", f"/api/demo/workspace/conversations/{conv['id']}/messages", {"role": "user", "content": "poison"}),
    ]:
        response = getattr(client, method)(path, headers=headers["bob"], json=body) if body is not None else getattr(client, method)(path, headers=headers["bob"])
        assert response.status_code == 404, (method, path, response.status_code, response.text)

    assert client.get(
        "/api/demo/workspace/conversations", headers=headers["bob"]
    ).json()["conversations"] == []
    assert client.get(
        "/api/demo/workspace/projects", headers=headers["bob"]
    ).json()["projects"] == []
    assert [p["id"] for p in client.get(
        "/api/demo/workspace/projects", headers=headers["alice"]
    ).json()["projects"]] == [project["id"]]
