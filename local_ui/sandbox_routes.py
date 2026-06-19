# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Token-gated routes for the execution sandbox (Phase 2).

Real code execution, so it is locked exactly like the operator surface:
  1. Path is ``/api/sandbox/*`` — nginx never forwards it to the public demo, so it
     is reachable only on loopback (or an SSH tunnel / the owner's own server).
  2. DISABLED unless ``SANDBOX_SECRET`` is set, and every call must carry
     ``Authorization: Bearer <secret>``.
The anonymous public workspace therefore keeps showing "Sandbox not connected" — the
engine is real and ready, but command execution is never exposed to the open internet.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from pydantic import BaseModel

from local_ui.sandbox import Sandbox, SandboxError


class RunReq(BaseModel):
    command: str
    timeout: int = 120


class WriteReq(BaseModel):
    path: str
    content: str
    reason: str = ""


class CloneReq(BaseModel):
    repo_url: str


def register_sandbox_routes(app: Any, root: str, secret_env: str = "SANDBOX_SECRET") -> None:
    from fastapi import Header, HTTPException

    sandboxes: Dict[str, Sandbox] = {}

    def _auth(authorization: Optional[str]) -> None:
        secret = os.environ.get(secret_env)
        if not secret:
            raise HTTPException(status_code=503,
                                detail=f"sandbox disabled — set {secret_env} to enable")
        if authorization != f"Bearer {secret}":
            raise HTTPException(status_code=401, detail="unauthorized")

    def _sb(sid: str) -> Sandbox:
        sb = sandboxes.get(sid)
        if sb is None:
            raise HTTPException(status_code=404, detail="unknown sandbox")
        return sb

    @app.get("/api/sandbox/health")
    def sandbox_health():
        # Honest capability probe (no secret needed): is exec enabled on this host?
        return {"enabled": bool(os.environ.get(secret_env)),
                "note": "set SANDBOX_SECRET + send Bearer token; never public"}

    @app.post("/api/sandbox/create")
    def create(authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        sb = Sandbox(root)
        sandboxes[sb.id] = sb
        return sb.state()

    @app.post("/api/sandbox/{sid}/run")
    def run(sid: str, req: RunReq, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return _sb(sid).run(req.command, timeout=min(req.timeout, 600))

    @app.post("/api/sandbox/{sid}/write")
    def write(sid: str, req: WriteReq, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        try:
            return _sb(sid).write_file(req.path, req.content, reason=req.reason)
        except SandboxError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/sandbox/{sid}/read")
    def read(sid: str, path: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        try:
            return {"path": path, "content": _sb(sid).read_file(path)}
        except SandboxError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.get("/api/sandbox/{sid}/files")
    def files(sid: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return {"files": _sb(sid).list_files()}

    @app.post("/api/sandbox/{sid}/clone")
    def clone(sid: str, req: CloneReq, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        try:
            return _sb(sid).clone(req.repo_url)
        except SandboxError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/sandbox/{sid}/detect")
    def detect(sid: str, sub: str = "", authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return _sb(sid).detect_project(sub=sub)

    @app.get("/api/sandbox/{sid}/diff")
    def diff(sid: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return _sb(sid).git_diff()

    @app.post("/api/sandbox/{sid}/snapshot")
    def snapshot(sid: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return {"snapshot": _sb(sid).snapshot()}

    @app.post("/api/sandbox/{sid}/rollback")
    def rollback(sid: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return {"rolled_back": _sb(sid).rollback()}

    @app.get("/api/sandbox/{sid}/state")
    def state(sid: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return _sb(sid).state()

    @app.get("/api/sandbox/{sid}/commands")
    def commands(sid: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return {"commands": _sb(sid).commands}

    @app.get("/api/sandbox/{sid}/changes")
    def changes(sid: str, authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        return {"changes": _sb(sid).changes}
