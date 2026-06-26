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
from typing import Any, Deque, Dict, Iterator, List, Optional

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
        # NO CAPABILITY BUDGETS. The controller — never a token/segment cap —
        # decides when an answer is done. These ceilings are set so high they are
        # effectively unlimited for real use (they exist only so a runaway loop has
        # SOME backstop); the only remaining "limit" is a thin anti-DoS rate guard on
        # the shared PUBLIC box, which does not apply at all on your own machine.
        # LEAN when sovereign/local: a slow on-device model shouldn't do 40 sequential
        # draft calls before answering — it answers in 1-2 and stays snappy. The
        # uncertainty control still runs; it just doesn't pay for cloud-speed drafting.
        _lean = os.environ.get("LOLM_SOVEREIGN", "").strip() in ("1", "true", "yes", "on") \
            or os.environ.get("LOLM_LEAN", "").strip() in ("1", "true", "yes", "on")
        self.max_segments = _int_env("DEMO_MAX_SEGMENTS", 2 if _lean else 40)
        self.segment_tokens = _int_env("DEMO_SEGMENT_TOKENS", 256 if _lean else 512)
        self.final_tokens = _int_env("DEMO_FINAL_TOKENS", 1200 if _lean else 32000)
        self.max_retrieves = _int_env("DEMO_MAX_RETRIEVES", 12)
        self.max_verifies = _int_env("DEMO_MAX_VERIFIES", 10)
        self.max_branches = _int_env("DEMO_MAX_BRANCHES", 6)
        self.branch_width = _int_env("DEMO_BRANCH_WIDTH", 4)
        # anti-abuse only (shared box); set DEMO_RATE_PER_HOUR=0 on your own machine.
        self.rate_per_hour = _int_env("DEMO_RATE_PER_HOUR", 100000)
        self.command_chars = _int_env("DEMO_COMMAND_CHARS", 500000)
        self.reasoner = os.environ.get("DEMO_REASONER", "local")  # local | workers_ai | claude

    def to_dict(self) -> Dict[str, int]:
        return dict(self.__dict__)


class DemoRunRequest(BaseModel):
    command: str
    session_id: Optional[str] = None   # opt-in long-form conversation key
    sources: Optional[str] = None      # BYO grounding text — answer only from this
    history: Optional[List[Dict[str, str]]] = None  # prior turns [{role,content},…]
                                       # for in-conversation memory (the workspace
                                       # passes the open conversation's transcript)
    user_memory: Optional[List[str]] = None  # durable facts about the user, recalled
                                       # across conversations (cross-session memory)


class DemoGate:
    """Single-flight lease plus per-IP rolling-hour rate limit.

    The lease (not a bare lock) is deliberate: a public client can vanish
    before the response generator ever runs, in which case no ``finally``
    fires and a plain lock would stay held forever. A lease records when the
    run started and is considered stale — and taken over — after
    ``max_run_seconds``, so the demo always self-heals.
    """

    def __init__(self, limits: DemoLimits):
        self.limits = limits
        self.max_run_seconds = _int_env("DEMO_MAX_RUN_SECONDS", 300)
        self._mutex = threading.Lock()
        self._lease_since: Optional[float] = None
        self.history: Dict[str, Deque[float]] = defaultdict(deque)
        self.runs_started = 0
        self.runs_completed = 0
        self.last_run_seconds: Optional[float] = None

    def try_acquire(self) -> bool:
        with self._mutex:
            now = time.time()
            if self._lease_since is not None and now - self._lease_since < self.max_run_seconds:
                return False
            self._lease_since = now
            return True

    def release(self) -> None:
        with self._mutex:
            self._lease_since = None

    @property
    def busy(self) -> bool:
        with self._mutex:
            return (self._lease_since is not None
                    and time.time() - self._lease_since < self.max_run_seconds)

    def allow(self, ip: str) -> Optional[str]:
        """Return a refusal reason, or None if the run may proceed."""
        if self.limits.rate_per_hour <= 0:
            return None                       # 0 = unlimited (your own machine)
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


def clamp_request(command: str, limits: DemoLimits,
                  session_id: Optional[str] = None,
                  sources: Optional[str] = None,
                  history: Optional[List[Dict[str, str]]] = None,
                  user_memory: Optional[List[str]] = None) -> NFETAgentRequest:
    # accept a sanitized session id (opaque token only) for long conversations
    sid = None
    if session_id and isinstance(session_id, str):
        sid = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or None
    # BYO grounding text: pasted by the user, capped to keep the demo bounded.
    src = sources.strip()[:24000] if (sources and isinstance(sources, str) and sources.strip()) else None
    # Conversation history → in-thread memory. Keep last 10 turns, roles sanitized,
    # content capped so a long thread can't blow the context budget.
    hist = None
    if isinstance(history, list) and history:
        hist = []
        for t in history[-10:]:
            if not isinstance(t, dict):
                continue
            role = "user" if t.get("role") == "user" else "assistant"
            content = str(t.get("content") or "").strip()[:1200]
            if content:
                hist.append({"role": role, "content": content})
        hist = hist or None
    # Cross-session memory: durable user facts, capped + length-bounded.
    umem = None
    if isinstance(user_memory, list) and user_memory:
        umem = [str(x).strip()[:300] for x in user_memory[:40] if str(x).strip()] or None
    return NFETAgentRequest(
        command=command.strip()[: limits.command_chars],
        reasoner=limits.reasoner,
        max_segments=limits.max_segments,
        segment_tokens=limits.segment_tokens,
        final_tokens=limits.final_tokens,
        max_retrieves=limits.max_retrieves,
        max_verifies=limits.max_verifies,
        max_branches=limits.max_branches,
        branch_width=limits.branch_width,
        allow_web=False,
        session_id=sid,
        sources=src,
        history=hist,
        user_memory=umem,
    )


_STATS_CACHE: Dict[str, Any] = {"key": None, "value": None}


def load_run_stats(log_path: Optional[Path]) -> Dict[str, Any]:
    """Durable run statistics straight from the improvement log.

    The gate's in-memory counters die on every service restart; the log is
    the ground truth. Cached by (mtime, size) so the endpoint stays cheap.
    """
    empty = {"total_runs": 0, "runs_24h": 0, "verdicts": {}, "controls": {},
             "decision_sources": {}, "head_decisions": 0}
    if not log_path or not log_path.exists():
        return empty
    stat = log_path.stat()
    cache_key = (str(log_path), stat.st_mtime_ns, stat.st_size)
    if _STATS_CACHE["key"] == cache_key:
        return _STATS_CACHE["value"]
    now = time.time()
    out = dict(empty, verdicts={}, controls={}, decision_sources={})
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "nfet_agent_run":
            continue
        out["total_runs"] += 1
        if float(event.get("timestamp", 0)) > now - 86400:
            out["runs_24h"] += 1
        proof = event.get("proof") or {}
        verdict = proof.get("verdict", "?")
        out["verdicts"][verdict] = out["verdicts"].get(verdict, 0) + 1
        for key, val in (proof.get("control_counts") or {}).items():
            out["controls"][key] = out["controls"].get(key, 0) + int(val)
        for key, val in (proof.get("decision_sources") or {}).items():
            out["decision_sources"][key] = out["decision_sources"].get(key, 0) + int(val)
    out["head_decisions"] = out["decision_sources"].get("head", 0)
    out["control_visible_runs"] = sum(
        v for k, v in out["verdicts"].items()
        if k in ("nfet_control_visible", "nfet_finalize_visible")
    )
    _STATS_CACHE["key"] = cache_key
    _STATS_CACHE["value"] = out
    return out


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
                         model_ready_fn: Any = lambda: True,
                         log_path: Optional[Path] = None,
                         web_sources_fn: Any = None) -> DemoGate:
    limits = limits or DemoLimits()
    gate = DemoGate(limits)
    replays_dir = Path(replays_dir)
    if log_path is None:
        data_dir = os.environ.get("LOCAL_UI_DATA_DIR")
        if data_dir:
            log_path = Path(data_dir) / "improvement_log.jsonl"

    @app.get("/api/demo/stats")
    def demo_stats():
        return load_run_stats(log_path)

    @app.get("/api/demo/status")
    def demo_status():
        return {
            "model_ready": bool(model_ready_fn()),
            "busy": gate.busy,
            "limits": limits.to_dict(),
            "runs_started": gate.runs_started,
            "runs_completed": gate.runs_completed,
            "last_run_seconds": gate.last_run_seconds,
            "replays": len(load_replay_index(replays_dir).get("replays", [])),
        }

    @app.get("/api/demo/agent/level")
    def demo_agent_level():
        # Honest capabilities of THIS public, reactive demo surface. The L3-L5
        # control loop (ticks, gated tools, bounded persistence) is implemented
        # and tested in the operator surface + code — it is NOT this surface's
        # live mode, so this endpoint reports L2 and says so plainly.
        from lolm.agent.agent_state import compute_autonomy_level
        caps = {
            "receipts": True,             # every run emits a layered + control receipt
            "controller_actions": True,   # retrieve/verify/branch fire and are consumed
            "memory_goal_ticks": False,   # persistent tick loop runs in the operator, not here
            "tools": False,               # gated tools are loopback-only (operator)
            "bounded_persistent": False,  # bounded persistent loop is not the public mode
        }
        return {
            "surface": "public_demo",
            "level": compute_autonomy_level(caps),
            "capabilities": caps,
            "levels": {
                "L0_REACTIVE_ONLY": "answers prompts only",
                "L1_RECEIPT_MONITORED": "answers with uncertainty receipts",
                "L2_CONTROLLER_ACTIONS": "controller verifies/retrieves/branches during a run",
                "L3_MEMORY_GOAL_TICKS": "runs memory + goal ticks between prompts",
                "L4_TOOL_USING_AUTONOMY": "uses gated, outcome-verified tools in ticks",
                "L5_BOUNDED_PERSISTENT_AGENT": "maintains goals/memory/verification/scheduling/tools under budget + safety",
            },
            "note": ("This public demo runs at L2 — real controller actions with honest "
                     "receipts. The L3–L5 control loop (ticks, gated tools, bounded "
                     "persistence, hard human-gate) is implemented and tested in the "
                     "operator surface and the code, not in this reactive demo. This "
                     "endpoint reports the real level of THIS surface, never a higher one."),
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
        if not gate.try_acquire():
            return JSONResponse(
                {"error": "another live run is in progress on this little 2-vCPU box; "
                          "watch a replay while you wait"},
                status_code=429,
            )
        gate.record(ip)
        gate.runs_started += 1
        started = time.time()

        # COMBINE: search the live web on every prompt, feed the results in as the
        # agent's grounding, then run the NFET uncertainty-control theater OVER that
        # evidence — one run that BOTH searches the web AND shows measured self-control
        # (per-token uncertainty, the five control moves). web_sources_fn returns
        # (grounding_text, n_sources, titles); it degrades gracefully to no grounding.
        grounding, n_src, links = "", 0, []
        user_src = getattr(req, "sources", None)
        # Don't web-ground when the user pasted their OWN notes — that's strict BYO
        # mode (answer only from their material). Otherwise: always search the web.
        if web_sources_fn is not None and not user_src:
            try:
                grounding, n_src, links = web_sources_fn(req.command)
            except Exception:
                grounding, n_src, links = "", 0, []
        combined = "\n\n".join([s for s in (grounding, user_src) if s]) or None
        agent_req = clamp_request(req.command, limits,
                                  getattr(req, "session_id", None), combined,
                                  getattr(req, "history", None),
                                  getattr(req, "user_memory", None))
        # ADVISORY grounding: the web results are evidence to draw on, never a cage —
        # the agent answers from knowledge + evidence and never refuses "not in sources".
        if grounding and not user_src:
            agent_req.web_grounded = True

        # Honest fallback: if the web search found nothing usable AND the topic is
        # time-sensitive, still flag that the answer is from training memory.
        fresh = None
        if n_src == 0:
            try:
                from lolm.research.freshness import time_sensitivity, freshness_notice
                if time_sensitivity(req.command).get("risk") in ("high", "medium"):
                    fresh = freshness_notice(req.command)
            except Exception:
                fresh = None

        def events() -> Iterator[str]:
            try:
                # Show the web search up front; the agent then runs its theater,
                # checking these sources whenever its measured uncertainty spikes.
                if n_src:
                    yield sse_event("web_search", {"sources": n_src, "links": links[:6]})
                for item in agent.run_events(agent_req):
                    if fresh is not None and item.get("event") == "run_done":
                        yield sse_event("freshness", fresh)
                    yield sse_event(item["event"], item["data"])
                gate.runs_completed += 1
            except Exception as exc:  # surface as an SSE error, never a half-dead stream
                yield sse_event("error", {"error": str(exc)[:300]})
            finally:
                gate.last_run_seconds = round(time.time() - started, 2)
                gate.release()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    return gate
