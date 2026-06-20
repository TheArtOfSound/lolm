"""Public demo service for lolm.imagineqira.com.

Runs the workspace bound to localhost with the NFET agent and the demo gate.
nginx forwards ONLY `/api/demo/` from the public vhost — every other route
stays loopback-only. The model and the bootstrapped controller checkpoint
load in a background thread so the service is responsive immediately;
`/api/demo/status` reports `model_ready: false` until the load finishes
(the UI offers replays in the meantime).

Env:
    DEMO_PROFILE=qwen3_0_6b_smoke   DEMO_DEVICE=cpu
    DEMO_GRAFT_CKPT=runs/nfet_controller/bootstrap_qwen06b.pt
    DEMO_REPLAYS_DIR=site/replays   PORT=7866
    (plus the DEMO_* budget knobs from local_ui.public_demo)
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

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

# Optional frontier brain: a strong model (Llama 70B via Cloudflare Workers AI)
# writes, the local graft telemeters it. Activated when WORKERS_AI_URL/SECRET
# are set; otherwise the demo runs the local model directly.
FRONTIER = WorkersAIReasonerLoop(state_fn=lambda: STATE)

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
    frontier_loop=FRONTIER,
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
                                       web_route_events, gather_web_sources)
RESEARCH = make_research_pipeline(FRONTIER, ChatRequest, ChatMessage)

register_demo_routes(
    app, AGENT, REPLAYS_DIR,
    model_ready_fn=lambda: STATE.backbone is not None,
    # Combine: search the live web every prompt → ground the NFET agent on the
    # results → run the uncertainty-control theater over real evidence.
    web_sources_fn=lambda cmd: gather_web_sources(RESEARCH, cmd),
)

from local_ui.vault_routes import register_vault_routes
register_vault_routes(app, AGENT)

# Persistent agent workspace (Phase 1): durable conversations/projects + receipt
# inspectors. Real persistence; sandbox execution is honestly reported "not connected".
from local_ui.workspace_store import WorkspaceStore
from local_ui.workspace_routes import register_workspace_routes
WORKSPACE = WorkspaceStore(ROOT / "runs" / "workspace")
register_workspace_routes(app, WORKSPACE)

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


def _operator_chat(messages):
    """Drive the frontier reasoner (local fallback) for ONE planner turn → text."""
    msgs = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
    kwargs = dict(messages=msgs, max_new_tokens=320, temperature=0.3,
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
    # Prefer the 70B planner; fall back to the local model on any runtime failure
    # (quota/502/timeout) so the operator keeps planning instead of dying — the
    # same resilience the agent loop has.
    if FRONTIER.available():
        try:
            t = _drive(FRONTIER)
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
        planner=FrontierPlanner(_operator_chat),
        flywheel=FLYWHEEL,
        uncertainty_fn=_operator_uncertainty,
        max_steps=8,
    )


register_operator_routes(
    app, build_agent=_build_operator_agent, flywheel=FLYWHEEL,
    model_ready_fn=lambda: STATE.backbone is not None,
)


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
