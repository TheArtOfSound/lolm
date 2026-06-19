# Copyright (c) 2026 Qira LLC. All rights reserved.
"""HTTP routes for the persistent agent workspace (Phase 1).

Real persistence for conversations / projects / messages, plus HONEST capability
endpoints for the parts not built yet (sandbox execution, file diffs, PRs) that
return a `connected: false` state instead of pretending. The frontend renders those
as "Sandbox not connected" rather than fake terminal output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from local_ui.workspace_store import WorkspaceStore


class NewConversation(BaseModel):
    title: str = "New conversation"
    project_id: str = ""
    mode: str = "chat"
    owner: str = ""


class PatchConversation(BaseModel):
    title: Optional[str] = None
    archived: Optional[bool] = None


class NewMessage(BaseModel):
    role: str
    content: str
    model_used: str = ""
    receipt_id: str = ""
    verdict: str = ""
    meta: Dict[str, Any] = {}


class NewProject(BaseModel):
    name: str
    repo_url: str = ""
    framework: str = ""
    package_manager: str = ""
    scripts: List[str] = []


# The agent modes the workspace offers. Every mode is a LIVE agent behaviour — the
# 70B + LOLM reasons in that mode right now (writes code, debugs, audits, plans a
# release, verifies a receipt). `needs_exec` marks the modes that ALSO use the
# execution sandbox to actually run things; reasoning is live regardless, and the
# sandbox's connected/not state is shown separately (never faked).
AGENT_MODES = [
    {"key": "chat", "label": "Chat", "tools": ["model"], "connected": True, "needs_exec": False,
     "frame": ""},
    {"key": "research", "label": "Research", "tools": ["web_search", "memory"], "connected": True,
     "needs_exec": False, "frame": "Research the question across the live web and your learned memory; cite sources."},
    {"key": "code", "label": "Code", "tools": ["model", "sandbox"], "connected": True, "needs_exec": True,
     "frame": "Coding task. Write correct, runnable code with a brief explanation; if it's a fix, show the changed code/diff. When a sandbox is connected you can run it."},
    {"key": "debug", "label": "Debug", "tools": ["model", "sandbox"], "connected": True, "needs_exec": True,
     "frame": "Debugging task. Diagnose the issue, name the most likely root cause, and give the precise fix. Interpret any error/stack-trace provided."},
    {"key": "repo_audit", "label": "Repo audit", "tools": ["model", "sandbox"], "connected": True, "needs_exec": True,
     "frame": "Code review / audit. Identify real bugs, security risks, and concrete improvements, each with a short reason. No vague nits."},
    {"key": "build_test", "label": "Build/Test", "tools": ["model", "sandbox"], "connected": True, "needs_exec": True,
     "frame": "Build/test help. Say exactly what to run, and interpret any output or failure provided. When a sandbox is connected the commands can actually run."},
    {"key": "package_release", "label": "Package release", "tools": ["model", "sandbox"], "connected": True, "needs_exec": True,
     "frame": "Release prep. Help with semver bump, changelog, and a safe publish checklist (provenance, canary, smoke). Flag anything irreversible."},
    {"key": "receipt_verify", "label": "Receipt verify", "tools": ["verifier", "vault"], "connected": True,
     "needs_exec": False, "frame": "Verify the most recent run receipt: explain what it proves, what it does NOT prove, and whether it can be QEV-sealed."},
]


def register_workspace_routes(app: Any, store: WorkspaceStore) -> None:

    def _owner(request: Request, body_owner: str = "") -> str:
        return (body_owner or request.headers.get("X-Workspace-Owner", "")).strip()[:64]

    # ── conversations ────────────────────────────────────────────────────────
    @app.post("/api/demo/workspace/conversations")
    def create_conversation(req: NewConversation, request: Request):
        return store.create_conversation(title=req.title, project_id=req.project_id,
                                         mode=req.mode, owner=_owner(request, req.owner))

    @app.get("/api/demo/workspace/conversations")
    def list_conversations(request: Request, archived: bool = False,
                           project_id: str = "", q: str = ""):
        return {"conversations": store.list_conversations(
            owner=_owner(request), include_archived=archived,
            project_id=project_id, query=q)}

    @app.get("/api/demo/workspace/conversations/{conv_id}")
    def get_conversation(conv_id: str):
        c = store.get_conversation(conv_id)
        if not c:
            return JSONResponse({"error": "unknown conversation"}, status_code=404)
        return c

    @app.patch("/api/demo/workspace/conversations/{conv_id}")
    def patch_conversation(conv_id: str, req: PatchConversation):
        out = None
        if req.title is not None:
            out = store.rename_conversation(conv_id, req.title)
        if req.archived is not None:
            out = store.set_archived(conv_id, req.archived)
        if out is None:
            return JSONResponse({"error": "unknown conversation"}, status_code=404)
        return out

    @app.post("/api/demo/workspace/conversations/{conv_id}/messages")
    def append_message(conv_id: str, req: NewMessage):
        msg = store.append_message(conv_id, req.role, req.content,
                                   model_used=req.model_used, receipt_id=req.receipt_id,
                                   verdict=req.verdict, meta=req.meta)
        if msg is None:
            return JSONResponse({"error": "unknown conversation"}, status_code=404)
        return msg

    # ── projects ─────────────────────────────────────────────────────────────
    @app.post("/api/demo/workspace/projects")
    def create_project(req: NewProject):
        return store.create_project(req.name, repo_url=req.repo_url, framework=req.framework,
                                    package_manager=req.package_manager, scripts=req.scripts)

    @app.get("/api/demo/workspace/projects")
    def list_projects():
        return {"projects": store.list_projects()}

    # ── modes + honest capability state ──────────────────────────────────────
    @app.get("/api/demo/workspace/modes")
    def modes():
        return {"modes": AGENT_MODES}

    @app.get("/api/demo/workspace/sandbox/status")
    def sandbox_status():
        # Honest: the Phase-2 execution engine EXISTS (real command exec, file diffs,
        # clone, rollback — all recorded), but it is token-gated and never exposed on
        # the public path, so for anonymous visitors it reports "not connected". It
        # lights up only on loopback with SANDBOX_SECRET. No faking either way.
        import os as _os
        exec_enabled = bool(_os.environ.get("SANDBOX_SECRET"))
        return {
            "connected": exec_enabled,
            "engine_built": True,
            "reason": ("Sandbox engine is built (real command execution, file diffs, "
                       "clone, rollback — every action recorded) but command execution "
                       "is token-gated and never exposed to anonymous public traffic. "
                       "Enable on loopback with SANDBOX_SECRET + a Bearer token."),
            "available": {"conversations": True, "projects": True, "receipts": True,
                          "memory": True, "web_search": True,
                          "command_execution": exec_enabled, "file_diffs": exec_enabled,
                          "repo_clone": exec_enabled, "rollback": exec_enabled,
                          "github_pr": False, "qev_seal_live": False},
            "phase": 2,
        }

    @app.get("/api/demo/workspace/stats")
    def workspace_stats():
        return store.stats()
