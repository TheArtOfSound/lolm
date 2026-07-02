# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Public endpoint for the LOLM Operator — the 70B drives a multi-tool agent loop
over a fresh bwrap-jailed virtual workspace, streamed live.

POST /api/demo/agent/run {goal} -> SSE of plan/tool_call/file_changed/command_*/
web_result/operator_done. Public + rate-limited; every command runs isolated (no host
FS / network), exactly like the public code sandbox. The model only proposes one
action per step — the loop is the sole thing that touches the sandbox.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from local_ui.agent_operator import AgentOperator
from local_ui.sandbox import Sandbox, _HAS_BWRAP

# A PERSISTENT workspace id: client-generated, so each visitor gets their own project
# that survives across operator runs (files accumulate — build, come back, keep going).
# Strictly validated so it can't traverse paths; absent/invalid → ephemeral one-shot.
_WS_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
_WS_TTL_S = int(os.environ.get("LOLM_WORKSPACE_TTL", str(24 * 3600)))   # reap idle workspaces


def _reap_workspaces(root: str) -> None:
    """Delete persistent workspaces untouched past the TTL — bounds disk without killing
    active projects. Cheap: runs at the start of each operator call."""
    base = Path(root)
    if not base.exists():
        return
    now = time.time()
    for d in base.glob("ws_*"):
        try:
            if d.is_dir() and now - d.stat().st_mtime > _WS_TTL_S:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
                snap = d.parent / f"{d.name}.snap"
                if snap.exists():
                    shutil.rmtree(snap, ignore_errors=True)
        except Exception:
            pass

# Owner sovereignty: on a machine WITHOUT the bwrap jail (e.g. macOS), the owner can opt
# into UNJAILED operator execution with LOLM_OPERATOR_LOCAL=1. This is gated to direct
# loopback requests only (never a proxied/public one — nginx adds x-forwarded-for), so a
# deployed public box can never be flipped into unjailed mode by a remote caller. The
# sandbox deny-list still blocks destructive/exfil commands as defense-in-depth.
_LOCAL_OPT_IN = bool(os.environ.get("LOLM_OPERATOR_LOCAL"))


def _is_loopback(request: "Request") -> bool:
    if request.headers.get("x-forwarded-for"):
        return False
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost", "")


class OperatorGoal(BaseModel):
    goal: str
    max_steps: int = 14
    workspace: str = ""          # persistent project id (client-generated); "" = ephemeral


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def register_agent_routes(app: Any, root: str,
                          chat_fn: Optional[Callable[[List[Dict[str, str]]], str]],
                          search_fn: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
                          fetch_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
                          runs_per_min: int = 4) -> None:
    rate: Dict[str, List[float]] = {}

    def _ip(req: Request) -> str:
        fwd = req.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "?"))

    @app.get("/api/demo/agent/health")
    def agent_health(request: Request):
        local = _LOCAL_OPT_IN and not _HAS_BWRAP and _is_loopback(request)
        return {"enabled": bool((_HAS_BWRAP or local) and chat_fn is not None),
                "isolated": _HAS_BWRAP, "local_mode": bool(local),
                "runs_per_min": runs_per_min,
                "web": bool(search_fn is not None),
                "tools": ["list", "read", "write", "edit", "run", "search", "fetch", "done"],
                "note": "LOLM Operator: a goal-driven multi-tool agent over its own virtual "
                        "computer — lists/reads/writes/edits files, runs shell, searches and "
                        "fetches the web read-only, and verifies its own work. On the public "
                        "box commands run in a bwrap jail; on your own machine "
                        "LOLM_OPERATOR_LOCAL=1 runs them directly (loopback only)."}

    @app.post("/api/demo/agent/run")
    def agent_run(req: OperatorGoal, request: Request):
        local = _LOCAL_OPT_IN and not _HAS_BWRAP and _is_loopback(request)
        if not ((_HAS_BWRAP or local) and chat_fn is not None):
            return JSONResponse({"error": "the operator runs commands in a bwrap jail (Linux). "
                                 "On your own machine, set LOLM_OPERATOR_LOCAL=1 to run it "
                                 "UNJAILED (loopback only); the deny-list still blocks "
                                 "destructive/exfiltration commands."}, status_code=503)
        ip = _ip(request)
        now = time.time()
        rate[ip] = [t for t in rate.get(ip, []) if now - t < 60]
        if len(rate[ip]) >= runs_per_min:
            return JSONResponse({"error": f"rate limit {runs_per_min} operator runs/min"},
                                status_code=429)
        rate[ip].append(now)
        goal = (req.goal or "").strip()[:2000]
        if not goal:
            return JSONResponse({"error": "empty goal"}, status_code=400)

        # PERSISTENT workspace: a valid client id → a project that survives across runs
        # (files accumulate, you continue where you left off). Absent/invalid → ephemeral.
        _reap_workspaces(root)
        ws = (req.workspace or "").strip()
        persistent = bool(_WS_RE.match(ws))
        sb = Sandbox(root, session_id=("ws_" + ws) if persistent else None)
        existing = len(sb.list_files()) if persistent else 0
        op = AgentOperator(sb, chat_fn, search_fn=search_fn, fetch_fn=fetch_fn,
                           max_steps=min(max(req.max_steps, 1), 18), isolated=_HAS_BWRAP)

        def gen():
            yield _sse("workspace", {"workspace": ws if persistent else "",
                                     "persistent": persistent, "existing_files": existing})
            try:
                for ev in op.run(goal):
                    yield _sse(ev["event"], ev["data"])
            except Exception as exc:
                yield _sse("error", {"error": str(exc)[:200]})
            finally:
                if not persistent:          # keep persistent projects; only ephemerals are torn down
                    try:
                        sb.destroy()
                    except Exception:
                        pass

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/demo/agent/files")
    def agent_files(workspace: str = ""):
        """The persistent project's file tree — so you can browse what the operator built,
        across runs, like a real workspace. Read-only."""
        if not _WS_RE.match(workspace or ""):
            return {"workspace": "", "files": [], "note": "no persistent workspace"}
        sb = Sandbox(root, session_id="ws_" + workspace)
        files = sb.list_files(limit=400)
        return {"workspace": workspace, "files": files, "count": len(files),
                "project": sb.detect_project()}

    @app.get("/api/demo/agent/file")
    def agent_file(workspace: str = "", path: str = ""):
        """Read one file from a persistent project (path-guarded to the workspace)."""
        if not _WS_RE.match(workspace or ""):
            return JSONResponse({"error": "invalid workspace"}, status_code=400)
        try:
            sb = Sandbox(root, session_id="ws_" + workspace)
            return {"path": path, "content": sb.read_file(path)[:200_000]}
        except Exception as exc:
            return JSONResponse({"error": str(exc)[:160]}, status_code=404)
