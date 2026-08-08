"""Documentation boundary service for lolm.imagineqira.com.

The public product is the open-source, local-first CLI. nginx still forwards
the historical `/api/demo/` prefix to this process so old links receive an
explicit 410 migration response instead of silently exposing agent execution.
Only inert health and product-configuration endpoints remain public.

Env:
    DEMO_PROFILE=qwen3_0_6b_smoke   DEMO_DEVICE=cpu
    DEMO_GRAFT_CKPT=runs/nfet_controller/bootstrap_qwen06b.pt
    DEMO_REPLAYS_DIR=site/replays   PORT=7866
    (plus the DEMO_* budget knobs from local_ui.public_demo)
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from typing import Dict                          # noqa: E402  (module-level for FastAPI/pydantic
from fastapi import Request                       # noqa: E402   to resolve string annotations under
from fastapi.responses import JSONResponse        # noqa: E402   `from __future__ import annotations`)

from local_ui import byok
byok.load_into_env()   # BYOK: load ~/.lolm/keys.env into the env before brain/search read keys

from local_ui import usage_limits

from local_ui.cloud_brain import CloudBrain
from local_ui.nfet_agent import AgentDeps, NFETAgent, register_nfet_agent_routes
from local_ui.public_demo import register_demo_routes
from local_ui.workers_ai_reasoner import WorkersAIReasonerLoop
from local_ui.server import (
    ROOT,
    STATE,
    ChatMessage,
    ChatRequest,
    LoadRequest,
    MEMORY,
    app,
    append_improvement_event,
    generation_loop,
    load_model,
)

PROFILE = os.environ.get("DEMO_PROFILE", "qwen3_0_6b_smoke")
DEVICE = os.environ.get("DEMO_DEVICE", "cpu")
GRAFT_CKPT = os.environ.get("DEMO_GRAFT_CKPT", "runs/nfet_controller/bootstrap_qwen06b.pt")
REPLAYS_DIR = Path(os.environ.get("DEMO_REPLAYS_DIR", str(ROOT / "site" / "replays")))

# The public product is documentation/install-only. Keep the historical demo
# routes importable for local tests and private development, but reject public
# API access except for inert health/config tombstones. The npm CLI
# talks directly to the user's chosen provider and never needs these endpoints.
PUBLIC_DOC_ENDPOINTS = {
    "/api/demo/health",
    "/api/demo/product-config",
    "/api/public/product-config",
}


@app.middleware("http")
async def cli_only_public_surface(request: Request, call_next):
    isolated_test_client = (os.environ.get("LOLM_TEST_NO_BOOT") == "1"
                            and getattr(request.client, "host", "") == "testclient")
    if (request.url.path.startswith("/api/demo/")
            and request.url.path not in PUBLIC_DOC_ENDPOINTS
            and not isolated_test_client):
        return JSONResponse({
            "error": "PUBLIC_WEB_EXECUTION_RETIRED",
            "message": "LOLM runs locally from the open-source CLI.",
            "install": "npm install -g lolm-cli",
            "docs": "/install.html",
        }, status_code=410)
    return await call_next(request)

usage_limits.init(ROOT / "runs")   # compatibility no-op; local CLI is unmetered
from local_ui import receipt_sign
receipt_sign.init(ROOT / "runs")
from local_ui.api_key_routes import register_api_key_routes
register_api_key_routes(app)

# Optional frontier brain: a strong model (Llama 70B via Cloudflare Workers AI)
# writes, the local graft telemeters it. Activated when WORKERS_AI_URL/SECRET
# are set; otherwise the demo runs the local model directly.
FRONTIER = WorkersAIReasonerLoop(state_fn=lambda: STATE)

# SOVEREIGN brain: a capable model running on YOUR machine (Ollama / llama.cpp /
# LM Studio / MLX). When it's up, GEN prefers it and nothing leaves the box; the
# cloud is only a fallback (and refused entirely when LOLM_SOVEREIGN=1). This is the
# tether-cutting path — local generation + the same on-device NFET telemetry.
# (Named GEN to avoid the CloudBrain memory `BRAIN` below — they are different things:
#  GEN generates text; BRAIN is shared persistent memory.)
from local_ui.local_brain import LocalServerReasonerLoop, BestBrain, sovereign
from local_ui.claude_reasoner import ClaudeReasonerLoop
from local_ui.direct_providers import DirectProviderLoop
LOCAL = LocalServerReasonerLoop(state_fn=lambda: STATE)
CLAUDE = ClaudeReasonerLoop(state_fn=lambda: STATE)   # claude-opus-4-8 — the frontier voice
# DIRECT BYOK: the user's OWN Groq/Cerebras/OpenAI/Together/OpenRouter key,
# called straight from the origin — full power with zero gateway dependency.
DIRECT = DirectProviderLoop(state_fn=lambda: STATE)


class _CloudChain:
    """Cloud tier: the shared worker gateway first (box-identical behavior),
    else the user's own direct provider keys. Availability is live env, so a
    key saved in the panel upgrades the very next call."""

    def __init__(self, worker: Any, direct: Any):
        self.worker, self.direct = worker, direct

    def _pick(self) -> Any:
        return self.worker if self.worker.available() else self.direct

    def available(self) -> bool:
        return self.worker.available() or self.direct.available()

    def __call__(self, req: Any):
        yield from self._pick()(req)

    def stream_text(self, req: Any):
        return self._pick().stream_text(req)

    def generate_many(self, messages, models, max_tokens: int = 3600):
        return self._pick().generate_many(messages, models, max_tokens)


CLOUD = _CloudChain(FRONTIER, DIRECT)


class _ClaudeFirst:
    """Intelligence-first brain order: Claude (frontier) leads when ANTHROPIC_API_KEY is set
    and we're not in sovereign mode; otherwise the best available of local / Workers-AI 70B.
    The on-device NFET graft telemeters whichever model speaks, so the measured-uncertainty
    control + receipt machinery is identical no matter who's the voice. Force a tier with
    LOLM_BRAIN=claude|local|70b."""

    def __init__(self, claude: Any, fallback: Any):
        self.claude, self.fallback = claude, fallback

    def _claude_on(self) -> bool:
        pin = os.environ.get("LOLM_BRAIN", "").lower()
        if pin == "claude":
            return bool(os.environ.get("ANTHROPIC_API_KEY"))
        if pin in ("local", "70b", "workers", "cloud"):
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY")) and not sovereign()

    def active(self) -> str:
        return "claude" if self._claude_on() else self.fallback.active()

    def available(self) -> bool:
        return self._claude_on() or self.fallback.available()

    def __call__(self, req: Any):
        if self._claude_on():
            # RESILIENT: if Claude errors (429/quota/SDK missing) BEFORE producing a
            # real token, fall through to the cascade instead of dumping the error —
            # the user paid for a good answer, not for an error message. Once real
            # tokens have streamed we pass errors through (can't un-stream).
            emitted_real = False
            try:
                for ev in self.claude(req):
                    if not emitted_real and ev.get("event") == "error":
                        raise RuntimeError((ev.get("data") or {}).get("error", "claude failed"))
                    if ev.get("event") in ("token", "done"):
                        emitted_real = True
                    yield ev
                return
            except Exception:
                if emitted_real:
                    raise
                yield {"event": "phase", "data": {
                    "phase": "brain_fallback",
                    "note": "claude errored before answering — fell back to the cascade"}}
            # fall through to the cascade below
        yield from self.fallback(req)


GEN = _ClaudeFirst(CLAUDE, BestBrain(LOCAL, CLOUD))


def _resolve_reasoner() -> str:
    """Best brain available RIGHT NOW for the chat path ('auto' resolution).
    reasoner!='local' routes to GEN — the full _ClaudeFirst→BestBrain(LOCAL,
    CLOUD) chain (paid Claude > worker/direct cloud > explicit local OR
    auto-discovered evolved :11435). 'local' means the tiny in-process demo
    model — the last resort only, never the silent default it used to be."""
    if GEN._claude_on():
        return "claude"
    if LOCAL.available() or CLOUD.available():
        return "workers_ai"
    return "local"

# Shared cloud brain (Cloudflare D1): persistent memory + long-form sessions,
# accumulating across every user anywhere. Reuses the Workers-AI worker URL/
# secret unless BRAIN_URL/BRAIN_SECRET are set. No-ops gracefully if unset.
def _brain_base() -> str:
    u = os.environ.get("BRAIN_URL")
    if u:
        return u
    wa = os.environ.get("WORKERS_AI_URL", "")
    return wa.rsplit("/ai/generate", 1)[0] if wa else ""

BRAIN = CloudBrain(
    base_url=_brain_base(),
    secret=os.environ.get("BRAIN_SECRET") or os.environ.get("WORKERS_AI_SECRET", ""),
)

def _confidence(text: str):
    """Measured per-token confidence over the answer via the loaded graft —
    the unique LOLM capability. No-ops if no local model is loaded."""
    from lolm.confidence_map import confidence_spans
    return confidence_spans(STATE.backbone, STATE.graft, text)

# The autonomy flywheel: every run's (measured uncertainty, verified outcome)
# pair persists here; the calibrator + selective-risk bars are fit on it so the
# agent earns its autonomy from its own track record. Durable across restarts.
from lolm.flywheel import AutonomyFlywheel
FLYWHEEL = AutonomyFlywheel(ROOT / "runs" / "autonomy_flywheel.jsonl")

from lolm.autonomy import AutonomyGate
from lolm.agent.agent_state import compute_autonomy_level as _compute_level


def _gate_factory():
    """An autonomy gate using the live flywheel's calibrator (re-fit as outcomes
    accumulate). Safe read/reversible tools only; money/delete hard-gated."""
    return AutonomyGate(FLYWHEEL.calibrator())


def _system_level() -> str:
    """Honest level of THIS reactive demo surface: L2 — real controller actions
    (retrieve / verify / branch) with auditable receipts, during a run. The L3-L5
    control loop (between-prompt ticks, gated tools, bounded persistence) is
    implemented and tested in the operator surface + code, but it is NOT this
    surface's live mode, so a reactive answer's receipt must not claim it — and
    this matches what /api/demo/agent/level reports. Never claim a higher level
    than the run actually operated at."""
    return _compute_level({"receipts": True, "controller_actions": True})


AGENT = NFETAgent(AgentDeps(
    memory=MEMORY,
    ChatMessage=ChatMessage,
    ChatRequest=ChatRequest,
    generation_loop=generation_loop,
    append_event=append_improvement_event,
    head_trained_fn=lambda: STATE.head_trained,
    frontier_loop=GEN,
    cloud_brain=BRAIN,
    confidence_fn=_confidence,
    flywheel=FLYWHEEL,
    autonomy_level_fn=_system_level,
))

register_nfet_agent_routes(app, AGENT)
# Live web-research pipeline: real search (DuckDuckGo keyless / Brave / Tavily) +
# SSRF-safe fetch + 70B grounded answer + honest research receipt. Built BEFORE the
# demo routes so the MAIN agent can divert to it on currentness prompts (the real
# fix for "I asked for today's news and it didn't search").
from local_ui.research_service import (make_research_pipeline, register_research_routes,
                                       gather_web_sources)
RESEARCH = make_research_pipeline(GEN, ChatRequest, ChatMessage)

register_demo_routes(
    app, AGENT, REPLAYS_DIR,
    model_ready_fn=lambda: STATE.backbone is not None,
    # Combine: search the live web every prompt → ground the NFET agent on the
    # results → run the uncertainty-control theater over real evidence.
    web_sources_fn=lambda cmd: gather_web_sources(RESEARCH, cmd),
    # "auto" reasoner resolution: chat leads with the best brain available NOW
    # (paid Claude key > 70B cascade > local) instead of silently defaulting local.
    reasoner_resolver_fn=_resolve_reasoner,
    usage_fn=usage_limits.check_request,
)

from local_ui.vault_routes import register_vault_routes
register_vault_routes(app, AGENT)

# Persistent agent workspace (Phase 1): durable conversations/projects + receipt
# inspectors. Real persistence; sandbox execution is honestly reported "not connected".
from local_ui.workspace_store import WorkspaceStore
from local_ui.workspace_routes import register_workspace_routes
WORKSPACE = WorkspaceStore(ROOT / "runs" / "workspace")
# chat_fn (lazy) powers the cross-session memory extractor — _operator_chat is
# defined further down; the lambda resolves it at request time.
register_workspace_routes(app, WORKSPACE, chat_fn=lambda msgs: _operator_chat(msgs, purpose="utility"))

# Real execution sandbox (Phase 2): /api/sandbox/* — REAL command exec/file/diff/
# rollback, but DISABLED unless SANDBOX_SECRET is set and never forwarded by nginx,
# so anonymous public traffic can't reach it (no public RCE). The workspace shows
# "Sandbox not connected" until the owner enables it on loopback with a token.
from local_ui.sandbox_routes import register_sandbox_routes, register_public_sandbox_routes
register_sandbox_routes(app, str(ROOT / "runs" / "sandboxes"))
# PUBLIC code execution — every run jailed in a bwrap namespace (no host FS/net/PIDs)
# + rate-limited. Safe to expose because the isolation, not a token, is the boundary.
register_public_sandbox_routes(app, str(ROOT / "runs" / "pub_sandboxes"))

# Background research scheduler: runs watch-topic jobs on a cadence (bounded to
# one per check so it never hammers search), writing source-backed memory the
# live research endpoint can reuse. This makes "learning in the background" real.
from lolm.research.scheduler import build_scheduler
from local_ui import internet_tools as _itools
RESEARCH_SCHED = build_scheduler(_itools.web_search, _itools.fetch_url,
                                 RESEARCH.memory_store, state_dir=ROOT / "runs")
if not os.environ.get("LOLM_TEST_NO_BOOT"):
    try:
        RESEARCH_SCHED.start()
    except Exception:
        pass
register_research_routes(app, RESEARCH, gate=globals().get("GATE"), scheduler=RESEARCH_SCHED)

# Hugging Face daily-learning surface: ingest the AI dataset ecosystem daily →
# license/quality/poison/dedupe filter → source-backed memory + training-candidate
# queue. Weight training stays GATED (eval wall), so the receipt honestly reports
# model_weights_changed: false. This is "learns daily" you can actually prove.
from local_ui.hf_service import make_hf_service, register_hf_routes
HF_LEARN = make_hf_service(ROOT / "runs")
if not os.environ.get("LOLM_TEST_NO_BOOT"):
    try:
        HF_LEARN.start()
    except Exception:
        pass
register_hf_routes(app, HF_LEARN, gate=globals().get("GATE"))

# NFET control surface: public read-only decision math + deterministic
# system-state answers; loopback/token-guarded autonomy tick + state.
from local_ui.control_routes import register_control_routes
register_control_routes(
    app, agent_id="lolm-demo",
    live_stats_fn=lambda: (BRAIN.stats() if BRAIN.available() else {}),
    goals_fn=lambda st: MEMORY.get_goals(),
    gate_factory=_gate_factory,
    recall_fn=lambda q: (BRAIN.recall(q) if BRAIN.available() else []),
)


# ── Autonomous operator (Phase 3): a gated tool-runtime over the dev / ops /
# research verticals, driven by the same calibrated uncertainty as the agent.
# Disabled unless OPERATOR_SECRET is set, and loopback-only (nginx never forwards
# /api/operator/). The planner only PROPOSES tool calls; the gate + Operator
# decide what runs and hard-gate money/send/delete/deploy to a human. ───────────
from local_ui.operator import Operator
from local_ui.operator_loop import OperatorAgent
from local_ui.operator_planner import FrontierPlanner
from local_ui.operator_routes import register_operator_routes
from lolm.autonomy import AutonomyGate
from lolm.calibration import aggregate_uncertainty


def _operator_chat(messages, max_new_tokens=640, purpose="answer"):
    """Drive the frontier reasoner (local fallback) for ONE planner turn → text.

    max_new_tokens defaults high enough for the code agent to emit a full program /
    a complete HTML app in one turn (the visual builder asks for ~2600).

    purpose="utility" is the cost tier for background/mechanical turns (life ticks
    every 20 min, memory extraction, planner JSON) — it SKIPS the user's paid
    Claude key and uses local/cascade, unless LOLM_BRAIN=claude pins it. Quality-
    bearing turns (code, visual builds, the strict verifier) stay purpose="answer"."""
    msgs = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
    kwargs = dict(messages=msgs, max_new_tokens=max_new_tokens, temperature=0.3,
                  top_p=0.9, use_graft=False)
    try:
        req = ChatRequest(**kwargs, telemeter=False)
    except TypeError:
        req = ChatRequest(**kwargs)
    def _drive(loop) -> str:
        text = ""
        for ev in loop(req):
            if ev.get("event") == "done":
                text = ev.get("data", {}).get("response") or text
            elif ev.get("event") == "error":
                raise RuntimeError(ev.get("data", {}).get("error", "planner failed"))
        return text
    utility = (purpose == "utility"
               and os.environ.get("LOLM_BRAIN", "").lower() != "claude")
    brain = GEN.fallback if (utility and GEN._claude_on()) else GEN
    # Prefer the best brain (local sovereign model first, else cloud); fall back to
    # the tiny in-process model on any runtime failure (quota/502/timeout) so the
    # operator keeps planning instead of dying — the same resilience the agent loop has.
    if brain.available():
        try:
            t = _drive(brain)
            if t.strip():
                return t
        except Exception:
            pass
    return _drive(generation_loop)


def _operator_uncertainty(text: str) -> float:
    """Measured uncertainty for a planner step — re-read its reasoning via the graft."""
    from local_ui.claude_reasoner import telemetry_traces_from_text
    traces = telemetry_traces_from_text(STATE.backbone, STATE.graft, text or "")
    frames = [{"graft_entropy": t.get("graft_entropy", 0.0),
               "hidden_drift": t.get("hidden_drift", 0.0)} for t in traces]
    return aggregate_uncertainty(frames)


def _build_operator_agent() -> OperatorAgent:
    return OperatorAgent(
        operator=Operator(AutonomyGate(FLYWHEEL.calibrator())),
        planner=FrontierPlanner(lambda msgs, max_new_tokens=640: _operator_chat(msgs, max_new_tokens, purpose="utility")),
        flywheel=FLYWHEEL,
        uncertainty_fn=_operator_uncertainty,
        max_steps=8,
    )


register_operator_routes(
    app, build_agent=_build_operator_agent, flywheel=FLYWHEEL,
    model_ready_fn=lambda: STATE.backbone is not None,
)

# Agentic coding loop: the 70B writes code, runs it in the bwrap jail, reads the real
# failure, and fixes it — streamed live. Public + rate-limited; uses the same frontier
# chat as the operator planner (drives FRONTIER, falls back to the local model).
from local_ui.code_routes import register_code_routes


def _stream_backend():
    """Live pick for token streaming: the user's paid Claude leads, else the
    worker gateway, else their own direct provider keys. Re-evaluated per
    request so a key saved in the panel upgrades the next build."""
    if GEN._claude_on() and hasattr(CLAUDE, "stream_text"):
        return CLAUDE
    if FRONTIER.available():
        return FRONTIER
    return DIRECT


def _operator_stream(messages, max_new_tokens=640):
    """Token-delta stream for the visual builder, from the best available brain.
    Raises if none is configured; the route errors and the client falls back to
    the blocking endpoint (which runs the full GEN chain)."""
    msgs = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
    kwargs = dict(messages=msgs, max_new_tokens=max_new_tokens, temperature=0.3,
                  top_p=0.9, use_graft=False)
    try:
        req = ChatRequest(**kwargs, telemeter=False)
    except TypeError:
        req = ChatRequest(**kwargs)
    return _stream_backend().stream_text(req)


def _operator_gen_many(messages, models, max_tokens=3600):
    """Best-of-N fan-out for the visual ensemble — via the worker gateway or the
    user's own direct provider keys; plus, when a paid Claude key is set, ONE
    Claude candidate joins the race (the browser verdict stays the oracle)."""
    cands = CLOUD.generate_many(messages, models, max_tokens) or []
    if GEN._claude_on() and len(cands) < 4:
        t0 = time.time()
        try:
            text = _operator_chat(list(messages), max_new_tokens=min(int(max_tokens), 3600))
            cands.append({"model": "claude", "provider": "anthropic",
                          "text": text, "ms": int((time.time() - t0) * 1000)})
        except Exception as exc:
            cands.append({"model": "claude", "provider": "anthropic",
                          "error": str(exc)[:140], "ms": int((time.time() - t0) * 1000)})
    return cands


# HOT-APPLY: pass the stream/ensemble hooks UNCONDITIONALLY — availability is
# checked per request inside them, so worker keys saved in the Keys panel enable
# streaming + the brain ensemble immediately (the old import-time `if
# FRONTIER.available()` froze these off forever if keys were unset at boot).
register_code_routes(app, str(ROOT / "runs" / "code_sandboxes"), _operator_chat,
                     stream_fn=_operator_stream,
                     gen_many_fn=_operator_gen_many,
                     usage_fn=usage_limits.check_request,
                     nfet_state_fn=lambda: STATE)

# LOLM Operator: a general multi-tool agent (list/read/write/run/search) that pursues a
# GOAL over its own bwrap-jailed virtual workspace — plan -> act -> observe -> verify,
# streamed live. Public + rate-limited; every command isolated like the code sandbox.
from local_ui.agent_routes import register_agent_routes
from local_ui import internet_tools


def _operator_search(query: str):
    """Real keyless web search (Brave/Tavily/SearxNG/DuckDuckGo) -> the result list the
    operator expects ([{title,url,snippet}])."""
    try:
        return (internet_tools.web_search(query, limit=6) or {}).get("results", [])
    except Exception:
        return []


def _operator_fetch(url: str):
    """Read the full text of a public web page (SSRF-guarded in internet_tools)."""
    return internet_tools.fetch_url(url)


register_agent_routes(app, str(ROOT / "runs" / "agent_workspaces"), _operator_chat,
                      search_fn=_operator_search, fetch_fn=_operator_fetch)

# ── LIFE: the always-on pulse — LOLM keeps thinking when nobody's on the site ──
# The box's cron POSTs /api/demo/life/tick (loopback-only) every ~20min; each tick
# thinks with the best brain, may run ONE read-only search, and journals the pulse.
# GET /api/demo/life renders the living trail (honest: asleep until a pulse exists).
from local_ui.life import LifeEngine, register_life_routes  # noqa: E402
from local_ui.agent_routes import _is_loopback as _life_loopback  # noqa: E402

LIFE = LifeEngine(ROOT / "runs", MEMORY,
                  lambda msgs, max_new_tokens=640: _operator_chat(msgs, max_new_tokens, purpose="utility"),
                  search_fn=_operator_search,
                  interval_s=int(os.environ.get("LOLM_LIFE_INTERVAL", "1200")))
register_life_routes(app, LIFE, _life_loopback)

@app.get("/api/demo/brain")
def brain_status():
    """Which brain is generating — and whether anything leaves the machine.
    'local' = a model on your own box (sovereign); 'cloud' = the shared 70B."""
    active = GEN.active()
    return {
        "active": active,                       # local | cloud | none
        "sovereign": sovereign(),               # cloud refused entirely?
        "on_device": active == "local",         # nothing leaves the machine
        "local": {"configured": LOCAL.configured(), "available": LOCAL.available(),
                  "model": LOCAL.model or None, "url": LOCAL.url, "api": LOCAL.api},
        "cloud": {"available": (FRONTIER.available() if not sovereign() else False),
                  "model": FRONTIER.model.split("/")[-1]},
        "how_to_go_local": "run a capable open model locally (e.g. `ollama run "
                           "llama3.3:70b` or `qwen2.5:72b`), set LOLM_LOCAL_MODEL to its "
                           "name, and LOLM_SOVEREIGN=1 to refuse the cloud entirely.",
    }


@app.get("/api/demo/evolve")
def evolve_status():
    """Honest view of the two self-evolution loops — controller (judgment) and knowledge
    (the model's own weights). Reads the daemons' durable state; shows 'not running'
    truthfully if they aren't (never fabricates progress)."""
    def _state(p: str):
        try:
            return json.loads((ROOT / p).read_text())
        except Exception:
            return None
    def _recent(p: str, n: int = 8):
        try:
            lines = [l for l in (ROOT / p).read_text().splitlines() if l.strip()][-n:]
            return [json.loads(l) for l in lines]
        except Exception:
            return []
    def _queue(p: str) -> int:
        try:
            return sum(1 for l in (ROOT / p).read_text().splitlines() if l.strip())
        except Exception:
            return 0
    ctrl = _state("runs/evolve/state.json")
    know = _state("runs/evolve_knowledge/state.json")
    return {
        "running": bool(ctrl or know),
        "controller": {
            "active": ctrl is not None,
            "cycles": (ctrl or {}).get("cycle", 0),
            "promoted": (ctrl or {}).get("promoted", 0),
            "rejected": (ctrl or {}).get("rejected", 0),
            "best_accuracy": round((ctrl or {}).get("best_val_acc", 0.0), 4),
            "recent": _recent("runs/evolve/receipts.jsonl"),
        },
        "knowledge": {
            "active": know is not None,
            "cycles": (know or {}).get("cycle", 0),
            "promoted": (know or {}).get("promoted", 0),
            "rejected": (know or {}).get("rejected", 0),
            "facts_known": (know or {}).get("facts_known", 0),
            "queued": _queue("runs/evolve_knowledge/queue.jsonl"),
            "recent": _recent("runs/evolve_knowledge/receipts.jsonl"),
        },
        "note": ("evolves while this machine is awake. start the loops: "
                 "scripts/evolve_daemon.py (judgment) + scripts/evolve_knowledge_daemon.py "
                 "(knowledge, --serve)."),
    }


# ── BYOK: your own API keys, set from your own machine (loopback only) ──────────
from local_ui.agent_routes import _is_loopback as _loopback  # noqa: E402
from pydantic import BaseModel as _BM  # noqa: E402


class _KeysBody(_BM):
    keys: Dict[str, str] = {}


@app.get("/api/demo/keys")
def keys_status(request: Request):
    """Masked status of every supported key. Raw values are NEVER returned; the last-4
    preview is shown only to a direct loopback caller (your own machine)."""
    return byok.status(reveal_preview=_loopback(request))


def _key_writer(request: "Request") -> bool:
    """Who may write keys: your own machine (loopback), or the OWNER from anywhere
    via the shield's signed admin token. Public visitors still can't poison the
    shared box's keys."""
    from local_ui import usage_limits as _ul
    return _loopback(request) or _ul.is_admin(request.headers.get("x-lolm-admin", ""))


@app.post("/api/demo/keys")
def keys_set(body: _KeysBody, request: Request):
    """Set/clear your keys — loopback or the owner's admin token, so a public
    visitor can never write keys on a shared box. Writes ~/.lolm/keys.env
    (chmod 600) and the live environment."""
    if not _key_writer(request):
        return JSONResponse({"error": "keys can only be set from your own machine "
                             "(loopback) — or unlock the shield (bottom-left) if you own this box"},
                            status_code=403)
    n = byok.set_keys(body.keys or {})
    # HOT-APPLY: keys land in os.environ inside set_keys; the brains read env live
    # (properties) — force the local brain to re-probe, then report which brain now
    # leads so the UI can say "applied — brain now: X" instead of "restart to apply".
    try:
        LOCAL._healthy = None
    except Exception:
        pass
    return {"updated": n, "applied": True, "brain": GEN.active(),
            **byok.status(reveal_preview=True)}




class _AdminUnlockBody(_BM):
    password: str


@app.post("/api/demo/admin/unlock")
def admin_unlock(body: _AdminUnlockBody):
    """The shield: password → signed 30-day admin token (unlimited usage + key
    writes from anywhere). Compared as SHA-256 vs LOLM_ADMIN_PASS_SHA256 —
    plaintext is never stored or logged."""
    tok = usage_limits.admin_unlock(body.password or "")
    if not tok:
        time.sleep(0.8)                     # slow brute force a touch
        return JSONResponse({"error": "nope"}, status_code=403)
    return {"admin": tok, "days": 30}


@app.get("/api/demo/product-config")
@app.get("/api/public/product-config")  # alias; only /api/demo/* is nginx-proxied publicly
def public_product_config(request: Request):
    """Safe documentation-only product snapshot (no secrets or execution)."""
    return {
        "version": 2,
        "product": {
            "name": "LOLM",
            "tagline": "Local intelligence, under your control.",
            "publisher": "Qira LLC",
            "url": "https://lolm.imagineqira.com/",
            "license": "AGPL-3.0-or-later",
        },
        "execution": {"website": False, "cli": True, "hosted_api": False},
        "install": {"command": "npm install -g lolm-cli", "href": "/install.html"},
        "commercial_license": {"available": True,
                               "contact": "bryanleonard237@gmail.com"},
        "static_config": "/product-config.json",
    }


@app.get("/api/demo/health")
def public_health():
    """Simple liveness for the documentation boundary (not model readiness)."""
    return {
        "ok": True,
        "service": "lolm-docs-boundary",
        "ts": int(time.time()),
        "execution": {"website": False, "cli": True, "hosted_api": False},
        "install": "npm install -g lolm-cli",
        "website": "https://lolm.imagineqira.com/",
    }



@app.get("/api/demo/operator")
def public_operator_status():
    """Public, READ-ONLY view of the operator's earned autonomy — no secret, no
    tool execution. nginx forwards /api/demo/, so the showcase page can render
    the live flywheel + the per-tier bars the track record currently supports.
    The acting endpoint (/api/operator/run) stays loopback + token gated."""
    from lolm.autonomy import RISK_TIERS, HARD_HUMAN_GATE
    bars = {}
    for tier, alpha in RISK_TIERS.items():
        st = FLYWHEEL.selective_bar(alpha)
        bars[tier] = {"allowed_error": alpha, "feasible": bool(st.feasible),
                      "coverage": round(st.coverage, 3)}
    return {
        "flywheel": FLYWHEEL.stats(),
        "tiers": RISK_TIERS,
        "bars": bars,
        "hard_gated": sorted(HARD_HUMAN_GATE),
        "note": "read-only; the agent acts only on loopback with a token, and "
                "money/send/delete/deploy are hard-gated to a human regardless of confidence",
    }


def _load_model_background() -> None:
    ckpt = GRAFT_CKPT if GRAFT_CKPT and Path(GRAFT_CKPT).exists() else None
    started = time.time()
    print(f"[demo] loading {PROFILE} on {DEVICE} (ckpt={ckpt or 'none'})...", flush=True)
    try:
        info = load_model(LoadRequest(
            profile=PROFILE, device=DEVICE, graft_checkpoint=ckpt,
        ))
        print(f"[demo] model ready in {time.time() - started:.1f}s: "
              f"hidden={info.get('hidden_size')} head_trained={info.get('head_trained')}", flush=True)
    except Exception as exc:
        print(f"[demo] model load FAILED: {exc}", flush=True)


if not os.environ.get("LOLM_TEST_NO_BOOT"):   # tests import this module without booting
    threading.Thread(target=_load_model_background, daemon=True).start()


# Serve the static workspace from the SAME origin as the API (mounted LAST so all
# /api/* routes above take precedence). On the box this is redundant with nginx and
# harmless; locally it makes `python -m local_ui.server_public_demo` a self-contained
# workspace — so the owner can enable SANDBOX_SECRET and use Code mode in the browser
# at the same origin where /api/sandbox/ is reachable (loopback), with no public RCE.
try:
    from fastapi.staticfiles import StaticFiles
    _site = ROOT / "site"
    if _site.is_dir():
        app.mount("/", StaticFiles(directory=str(_site), html=True), name="site")
except Exception as _exc:  # never let a static-mount issue take down the API
    print(f"[demo] static mount skipped: {_exc}", flush=True)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "7866"))
    uvicorn.run(app, host=host, port=port)
