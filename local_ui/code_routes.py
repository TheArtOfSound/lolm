# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Public agentic-coding endpoint — the 70B drives the isolated sandbox in a loop.

POST /api/demo/code/run streams the real write→run→read→fix loop (code_agent) over a
fresh bwrap-jailed sandbox, driven by the frontier model. Public + rate-limited; every
command is isolated (no host FS/net) exactly like the public sandbox. The model only
proposes JSON actions — the loop is the sole thing that touches the sandbox.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from local_ui.code_agent import CodeAgent
from local_ui.sandbox import Sandbox, _HAS_BWRAP


class CodeTask(BaseModel):
    task: str
    max_steps: int = 8


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def register_code_routes(app: Any, root: str,
                         chat_fn: Optional[Callable[[List[Dict[str, str]]], str]],
                         runs_per_min: int = 6) -> None:
    rate: Dict[str, List[float]] = {}

    def _ip(req: Request) -> str:
        fwd = req.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "?"))

    @app.get("/api/demo/code/health")
    def code_health():
        return {"enabled": bool(_HAS_BWRAP and chat_fn is not None),
                "isolated": True, "runs_per_min": runs_per_min,
                "note": "the 70B writes code, runs it in a bwrap jail, reads the failure, "
                        "and fixes it — every command isolated (no host FS/network)"}

    @app.post("/api/demo/code/run")
    def code_run(req: CodeTask, request: Request):
        if not (_HAS_BWRAP and chat_fn is not None):
            return JSONResponse({"error": "agentic code execution unavailable on this host"},
                                status_code=503)
        ip = _ip(request)
        now = time.time()
        rate[ip] = [t for t in rate.get(ip, []) if now - t < 60]
        if len(rate[ip]) >= runs_per_min:
            return JSONResponse({"error": f"rate limit {runs_per_min} code runs/min"},
                                status_code=429)
        rate[ip].append(now)
        task = (req.task or "").strip()[:2000]
        if not task:
            return JSONResponse({"error": "empty task"}, status_code=400)

        sb = Sandbox(root)
        agent = CodeAgent(sb, chat_fn, max_steps=min(max(req.max_steps, 1), 10), isolated=True)

        def gen():
            try:
                for ev in agent.run(task):
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
