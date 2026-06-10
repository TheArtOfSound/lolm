"""Public demo gate for the NFET agent.

This is the only surface that should ever be exposed to the internet (nginx
forwards `/api/demo/` and nothing else). It wraps the agent with the guards a
shared 2-vCPU production box needs:

- **Clamped budgets** — whatever the client sends, segment counts and token
  budgets are clamped to demo limits set by environment variables.
- **Single flight** — one live run at a time, globally; concurrent requests
  get 429 with a retry hint instead of stacking CPU load.
- **Per-IP rate limit** — N live runs per rolling hour (X-Forwarded-For aware).
- **Replay library** — pre-recorded real runs served instantly, so the page
  works even while a live run is cooking or the model is loading.

Env knobs (defaults sized for the shared box):
    DEMO_MAX_SEGMENTS=3  DEMO_SEGMENT_TOKENS=28  DEMO_FINAL_TOKENS=96
    DEMO_MAX_RETRIEVES=1 DEMO_MAX_VERIFIES=1     DEMO_MAX_BRANCHES=1
    DEMO_BRANCH_WIDTH=2  DEMO_RATE_PER_HOUR=4    DEMO_COMMAND_CHARS=300
    DEMO_REPLAYS_DIR=site/replays
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterator, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from local_ui.nfet_agent import NFETAgent, NFETAgentRequest, sse_event


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class DemoLimits:
    def __init__(self) -> None:
        self.max_segments = _int_env("DEMO_MAX_SEGMENTS", 3)
        self.segment_tokens = _int_env("DEMO_SEGMENT_TOKENS", 28)
        self.final_tokens = _int_env("DEMO_FINAL_TOKENS", 96)
        self.max_retrieves = _int_env("DEMO_MAX_RETRIEVES", 1)
        self.max_verifies = _int_env("DEMO_MAX_VERIFIES", 1)
        self.max_branches = _int_env("DEMO_MAX_BRANCHES", 1)
        self.branch_width = _int_env("DEMO_BRANCH_WIDTH", 2)
        self.rate_per_hour = _int_env("DEMO_RATE_PER_HOUR", 4)
        self.command_chars = _int_env("DEMO_COMMAND_CHARS", 300)

    def to_dict(self) -> Dict[str, int]:
        return dict(self.__dict__)


class DemoRunRequest(BaseModel):
    command: str


class DemoGate:
    """Single-flight lock plus per-IP rolling-hour rate limit."""

    def __init__(self, limits: DemoLimits):
        self.limits = limits
        self.lock = threading.Lock()
        self.history: Dict[str, Deque[float]] = defaultdict(deque)
        self.runs_started = 0
        self.runs_completed = 0
        self.last_run_seconds: Optional[float] = None

    def allow(self, ip: str) -> Optional[str]:
        """Return a refusal reason, or None if the run may proceed."""
        now = time.time()
        window = self.history[ip]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= self.limits.rate_per_hour:
            return (
                f"rate limit: {self.limits.rate_per_hour} live runs per hour per visitor; "
                "try a replay, or come back in a bit"
            )
        return None

    def record(self, ip: str) -> None:
        self.history[ip].append(time.time())


def client_ip(request: Any) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def clamp_request(command: str, limits: DemoLimits) -> NFETAgentRequest:
    return NFETAgentRequest(
        command=command.strip()[: limits.command_chars],
        reasoner="local",
        max_segments=limits.max_segments,
        segment_tokens=limits.segment_tokens,
        final_tokens=limits.final_tokens,
        max_retrieves=limits.max_retrieves,
        max_verifies=limits.max_verifies,
        max_branches=limits.max_branches,
        branch_width=limits.branch_width,
        allow_web=False,
    )


def load_replay_index(replays_dir: Path) -> Dict[str, Any]:
    index_path = replays_dir / "index.json"
    if not index_path.exists():
        return {"replays": []}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"replays": []}


def register_demo_routes(app: Any, agent: NFETAgent, replays_dir: Path,
                         limits: Optional[DemoLimits] = None,
                         model_ready_fn: Any = lambda: True) -> DemoGate:
    limits = limits or DemoLimits()
    gate = DemoGate(limits)
    replays_dir = Path(replays_dir)

    @app.get("/api/demo/status")
    def demo_status():
        return {
            "model_ready": bool(model_ready_fn()),
            "busy": gate.lock.locked(),
            "limits": limits.to_dict(),
            "runs_started": gate.runs_started,
            "runs_completed": gate.runs_completed,
            "last_run_seconds": gate.last_run_seconds,
            "replays": len(load_replay_index(replays_dir).get("replays", [])),
        }

    @app.get("/api/demo/replays")
    def demo_replays():
        return load_replay_index(replays_dir)

    @app.get("/api/demo/replay/{replay_id}")
    def demo_replay(replay_id: str):
        safe = "".join(c for c in replay_id if c.isalnum() or c in "-_")[:80]
        path = replays_dir / f"{safe}.json"
        if not path.exists():
            return JSONResponse({"error": "unknown replay"}, status_code=404)
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post("/api/demo/run/stream")
    def demo_run_stream(req: DemoRunRequest, request: Request):
        if not req.command.strip():
            return JSONResponse({"error": "empty command"}, status_code=400)
        if not model_ready_fn():
            return JSONResponse(
                {"error": "the local model is still loading; try a replay"},
                status_code=503,
            )
        ip = client_ip(request)
        refusal = gate.allow(ip)
        if refusal:
            return JSONResponse({"error": refusal}, status_code=429)
        if not gate.lock.acquire(blocking=False):
            return JSONResponse(
                {"error": "another live run is in progress on this little 2-vCPU box; "
                          "watch a replay while you wait"},
                status_code=429,
            )
        gate.record(ip)
        gate.runs_started += 1
        agent_req = clamp_request(req.command, limits)
        started = time.time()

        def events() -> Iterator[str]:
            try:
                for item in agent.run_events(agent_req):
                    yield sse_event(item["event"], item["data"])
                gate.runs_completed += 1
            except Exception as exc:  # surface as an SSE error, never a half-dead stream
                yield sse_event("error", {"error": str(exc)[:300]})
            finally:
                gate.last_run_seconds = round(time.time() - started, 2)
                gate.lock.release()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    return gate
