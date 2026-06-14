# Copyright (c) 2026 Qira LLC. All rights reserved.
"""HTTP surface for the NFET control core + autonomy tick.

Public, read-only (safe to expose; no side effects):
    POST /api/demo/control/decide   {signals}            -> DecisionPacket
    POST /api/demo/system-state      {question, ...}      -> metadata answer

Loopback / token-guarded (mutates agent state; nginx never forwards these, and
they additionally require AGENT_TICK_SECRET when set):
    POST /api/agent/tick   {trigger}                      -> run one autonomy tick
    GET  /api/agent/state                                 -> persisted AgentState
"""

import os
from typing import Any, Callable, Dict, Optional

# Module-level so FastAPI can resolve the `request: Request` annotation. (A local
# import + lazy annotations would make FastAPI treat `request` as a query param.)
from fastapi import Request
from fastapi.responses import JSONResponse


def register_control_routes(app: Any, *, agent_id: str = "lolm-demo",
                            memory_fn: Optional[Callable] = None,
                            goals_fn: Optional[Callable] = None,
                            live_stats_fn: Optional[Callable] = None,
                            gate_factory: Optional[Callable] = None,
                            recall_fn: Optional[Callable] = None) -> None:
    from lolm.control.nfet import decide
    from lolm.control.signals import ControlSignals
    from lolm.control.system_state import answer_system_state_question
    from lolm.agent.agent_state import load_agent_state, compute_autonomy_level
    from lolm.agent.autonomy_tick import autonomy_tick, TickInput
    from lolm.agent.tools import ToolExecutor, CalcTool, ClockTool, RecallTool
    from lolm.agent.persistent import PersistentAgent, Budget

    secret = os.environ.get("AGENT_TICK_SECRET", "")

    def _build_executor():
        """A gated, outcome-verified safe-tool executor using the live flywheel
        calibrator. None if no gate is wired (then the system is at most L3)."""
        if gate_factory is None:
            return None
        tools = [CalcTool(), ClockTool()]
        if recall_fn is not None:
            tools.append(RecallTool(recall_fn))
        return ToolExecutor.of(gate_factory(), tools)

    def _level() -> str:
        return compute_autonomy_level({
            "receipts": True, "controller_actions": True, "memory_goal_ticks": True,
            "tools": gate_factory is not None,
            "bounded_persistent": gate_factory is not None,
        })

    def _authed(request: Request) -> bool:
        # No secret configured -> rely on nginx loopback isolation (these routes
        # are never forwarded publicly). With a secret, require it.
        if not secret:
            return True
        return request.headers.get("authorization", "") == f"Bearer {secret}"

    @app.post("/api/demo/control/decide")
    async def control_decide(request: Request):
        body = await _json(request)
        sig = ControlSignals.from_dict(body.get("signals") or body)
        dp = decide(sig, input_type=body.get("inputType", "scheduled_tick"))
        return dp.to_dict()

    @app.post("/api/demo/system-state")
    async def system_state(request: Request):
        body = await _json(request)
        live = body.get("currentStats")
        if live is None and live_stats_fn is not None:
            try:
                live = live_stats_fn()
            except Exception:
                live = None
        ans = answer_system_state_question(
            body.get("question", ""), current_stats=live,
            receipt_snapshot=body.get("receiptSnapshot"),
            decision_packet=body.get("decisionPacket"))
        if ans is None:
            return {"source": "not_system_state", "answer": None,
                    "hint": "not an internal-state question; answer normally"}
        return ans

    @app.post("/api/agent/tick")
    async def agent_tick(request: Request):
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await _json(request)
        live = (live_stats_fn() if live_stats_fn else {}) or {}
        out = autonomy_tick(
            TickInput(agent_id, body.get("trigger", "manual_tick"), liveStats=live),
            memory_fn=(lambda st: live) if memory_fn is None else memory_fn,
            goals_fn=goals_fn)
        return out

    @app.get("/api/agent/state")
    async def agent_state(request: Request):
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return load_agent_state(agent_id).to_dict()

    @app.get("/api/demo/agent/level")
    async def agent_level(request: Request):
        # Public, read-only: the system's HONEST autonomy level + the tools it can
        # run on its own (safe/read-reversible only; money/delete stay human-gated).
        ex = _build_executor()
        return {"autonomyLevel": _level(), "toolsWired": gate_factory is not None,
                "tools": ex.names() if ex is not None else [],
                "hardGatedToHuman": ["payment", "transfer", "trade", "send",
                                     "email", "delete", "deploy"]}

    @app.post("/api/agent/run")
    async def agent_run(request: Request):
        # Loopback/token-guarded: run one BOUNDED persistent session (L5). Each
        # tick is gated + receipt-chained; every tool call is outcome-verified;
        # the run STOPS at the budget, a safety limit, or idle convergence.
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await _json(request)
        agent = PersistentAgent(agent_id, tool_executor=_build_executor(),
                                goals_fn=goals_fn)
        budget = Budget(maxActions=int(body.get("maxActions", 4)),
                        maxToolCalls=int(body.get("maxToolCalls", 3)))
        return agent.run(max_ticks=int(body.get("maxTicks", 6)), budget=budget,
                         plan=body.get("plan"), autonomy_level=_level())


async def _json(request) -> Dict[str, Any]:
    try:
        return await request.json()
    except Exception:
        return {}
