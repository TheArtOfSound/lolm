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


class VisualTask(BaseModel):
    task: str


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_html(raw: str) -> Optional[str]:
    """Pull a complete HTML document out of the model's reply (tolerates fences/prose)."""
    if not raw:
        return None
    t = raw.strip()
    if "```" in t:
        import re
        m = re.search(r"```(?:html)?\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
        if m and ("<" in m.group(1)):
            t = m.group(1).strip()
    low = t.lower()
    start = low.find("<!doctype")
    if start < 0:
        start = low.find("<html")
    if start < 0:
        # bare fragment (just <canvas>/<script>…) → wrap into a minimal dark document
        if "<" in t and ("<script" in low or "<canvas" in low or "<div" in low or "<svg" in low):
            return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<style>html,body{margin:0;height:100%;background:#0a0c10;color:#e2e8f0;"
                    "font-family:system-ui}</style></head><body>" + t + "</body></html>")
        return None
    end = low.rfind("</html>")
    return t[start:end + 7] if end > start else t[start:]


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

    @app.post("/api/demo/code/visual")
    def code_visual(req: VisualTask, request: Request):
        """Build a COMPLETE self-contained HTML app for a visual/interactive task.

        The browser is the safe visual runtime: the returned HTML runs in a
        sandboxed iframe (allow-scripts only — no network, no parent access), so a
        game/animation/UI is actually playable, not just printed as text.
        """
        if chat_fn is None:
            return JSONResponse({"error": "visual builder unavailable on this host"},
                                status_code=503)
        ip = _ip(request)
        now = time.time()
        rate[ip] = [t for t in rate.get(ip, []) if now - t < 60]
        if len(rate[ip]) >= runs_per_min:
            return JSONResponse({"error": f"rate limit {runs_per_min} builds/min"},
                                status_code=429)
        rate[ip].append(now)
        task = (req.task or "").strip()[:2000]
        if not task:
            return JSONResponse({"error": "empty task"}, status_code=400)

        system = (
            "You build ONE complete, self-contained HTML document that implements the "
            "user's visual or interactive task. Output ONLY the HTML — start with "
            "<!DOCTYPE html> and nothing before it, no prose, no markdown fences.\n"
            "RULES:\n"
            "- Inline ALL CSS in <style> and ALL JavaScript in <script>. One file.\n"
            "- NO external resources: no CDNs, no <script src=URL>, no <img src=URL>, no "
            "fetch/XHR, no imports, no web fonts. They are BLOCKED by the sandbox.\n"
            "- Use <canvas> or DOM + vanilla JS. Make it ACTUALLY WORK and be playable: "
            "wire keyboard/mouse handlers, a requestAnimationFrame game loop, score, and "
            "on-screen instructions. Start automatically or on a key/click.\n"
            "- Fill the viewport; dark, clean styling. Make it fun and complete."
        )
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": f"TASK: {task}\n\nReturn the full HTML document now."}]
        try:
            raw = chat_fn(msgs, max_new_tokens=2600)
        except TypeError:
            raw = chat_fn(msgs)          # chat_fn without a token arg (tests)
        except Exception as exc:
            return JSONResponse({"error": f"generation failed: {exc}"[:200]}, status_code=502)
        html = _extract_html(raw)
        if not html or len(html) < 60:
            return JSONResponse({"error": "the model did not return a usable HTML app — try rephrasing"},
                                status_code=502)
        return {"html": html, "bytes": len(html)}
