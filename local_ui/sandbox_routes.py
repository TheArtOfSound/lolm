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
import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request   # MODULE level: `from __future__
from fastapi.responses import JSONResponse           # import annotations` makes
from pydantic import BaseModel                        # annotations strings that FastAPI
                                                      # resolves from module globals.
from local_ui.sandbox import Sandbox, SandboxError, _HAS_BWRAP


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


# ── PUBLIC isolated sandbox (/api/demo/sandbox/*) ────────────────────────────
# Reachable by anyone (nginx forwards /api/demo/), but EVERY command runs inside the
# bwrap namespace jail (no host FS / network / PIDs, ulimit caps) and is rate-limited.
# No token — but also no host reach. If bwrap is missing, execution is refused (never
# falls back to an un-jailed run on a public endpoint).
def register_public_sandbox_routes(app: Any, root: str) -> None:
    MAX_TOTAL, PER_IP, RUNS_PER_MIN, TTL = 40, 3, 30, 1800
    pool: Dict[str, Dict[str, Any]] = {}        # sid -> {sb, ip, created, runs:[ts]}

    def _ip(req: Request) -> str:
        fwd = req.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "?"))

    def _gc():
        now = time.time()
        for sid in [s for s, v in pool.items() if now - v["created"] > TTL]:
            try:
                pool[sid]["sb"].destroy()
            except Exception:
                pass
            pool.pop(sid, None)

    def _get(sid: str) -> Dict[str, Any]:
        v = pool.get(sid)
        if not v:
            raise SandboxError("unknown or expired sandbox")
        return v

    @app.get("/api/demo/sandbox/health")
    def pub_health():
        return {"enabled": _HAS_BWRAP, "isolated": True, "rate_limited": True,
                "limits": {"per_ip_sandboxes": PER_IP, "runs_per_min": RUNS_PER_MIN,
                           "ttl_seconds": TTL, "run_timeout_s": 15},
                "note": ("public code execution runs in a bwrap namespace jail — no "
                         "network, no host filesystem, no host processes")
                if _HAS_BWRAP else "isolation runtime (bwrap) not present — execution disabled"}

    @app.post("/api/demo/sandbox/create")
    def pub_create(request: Request):
        _gc()
        if not _HAS_BWRAP:
            return JSONResponse({"error": "code execution unavailable — no sandbox isolation on this host"}, status_code=503)
        ip = _ip(request)
        if len(pool) >= MAX_TOTAL:
            return JSONResponse({"error": "sandbox capacity reached — try again shortly"}, status_code=429)
        if sum(1 for v in pool.values() if v["ip"] == ip) >= PER_IP:
            return JSONResponse({"error": f"limit {PER_IP} sandboxes per visitor"}, status_code=429)
        sb = Sandbox(root)
        pool[sb.id] = {"sb": sb, "ip": ip, "created": time.time(), "runs": []}
        return {**sb.state(), "isolated": True}

    @app.post("/api/demo/sandbox/{sid}/run")
    def pub_run(sid: str, req: RunReq, request: Request):
        try:
            v = _get(sid)
        except SandboxError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        now = time.time()
        v["runs"] = [t for t in v["runs"] if now - t < 60]
        if len(v["runs"]) >= RUNS_PER_MIN:
            return JSONResponse({"error": f"rate limit {RUNS_PER_MIN} runs/min"}, status_code=429)
        v["runs"].append(now)
        return v["sb"].run(req.command, timeout=15, isolated=True)   # JAIL ENFORCED

    @app.post("/api/demo/sandbox/{sid}/write")
    def pub_write(sid: str, req: WriteReq):
        try:
            return _get(sid)["sb"].write_file(req.path, req.content, reason=req.reason)
        except SandboxError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.get("/api/demo/sandbox/{sid}/read")
    def pub_read(sid: str, path: str):
        try:
            return {"path": path, "content": _get(sid)["sb"].read_file(path)}
        except SandboxError as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    @app.get("/api/demo/sandbox/{sid}/files")
    def pub_files(sid: str):
        try:
            return {"files": _get(sid)["sb"].list_files()}
        except SandboxError as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    @app.get("/api/demo/sandbox/{sid}/state")
    def pub_state(sid: str):
        try:
            return {**_get(sid)["sb"].state(), "isolated": True}
        except SandboxError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
