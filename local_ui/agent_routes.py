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
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from local_ui.agent_operator import AgentOperator
from local_ui.sandbox import Sandbox, _HAS_BWRAP


class OperatorGoal(BaseModel):
    goal: str
    max_steps: int = 14


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def register_agent_routes(app: Any, root: str,
                          chat_fn: Optional[Callable[[List[Dict[str, str]]], str]],
                          search_fn: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
                          runs_per_min: int = 4) -> None:
    rate: Dict[str, List[float]] = {}

    def _ip(req: Request) -> str:
        fwd = req.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "?"))

    @app.get("/api/demo/agent/health")
    def agent_health():
        return {"enabled": bool(_HAS_BWRAP and chat_fn is not None),
                "isolated": True, "runs_per_min": runs_per_min,
                "tools": ["list", "read", "write", "run", "search", "done"],
                "note": "LOLM Operator: a goal-driven multi-tool agent over a sandboxed "
                        "virtual computer — lists/reads/writes/edits files, runs shell in a "
                        "bwrap jail (no host FS/network), searches the web read-only, and "
                        "verifies its own work before finishing."}

    @app.post("/api/demo/agent/run")
    def agent_run(req: OperatorGoal, request: Request):
        if not (_HAS_BWRAP and chat_fn is not None):
            return JSONResponse({"error": "the operator needs a sandbox jail (bwrap) — "
                                          "unavailable on this host"}, status_code=503)
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

        sb = Sandbox(root)
        op = AgentOperator(sb, chat_fn, search_fn=search_fn,
                           max_steps=min(max(req.max_steps, 1), 18), isolated=True)

        def gen():
            try:
                for ev in op.run(goal):
                    yield _sse(ev["event"], ev["data"])
            except Exception as exc:
                yield _sse("error", {"error": str(exc)[:200]})
            finally:
                try:
                    sb.destroy()
                except Exception:
                    pass

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
