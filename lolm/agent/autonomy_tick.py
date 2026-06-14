# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The autonomy tick — LOLM's persistent control loop between prompts.

A tick loads state, measures the control signals, runs the NFET controller, and
either takes an allowed action or idles — and writes a hash-chained receipt
either way. Idle is not failure; it is restraint, and it is recorded. Hooks
(memory_fn / goals_fn / signals_fn / execute_fn) are injected so the loop is
testable without the model or a live store, and so the same loop drives
scheduled, post-answer, and review ticks.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from lolm.agent.agent_state import AgentState, load_agent_state, persist_agent_state
from lolm.control.nfet import decide, NFETField
from lolm.control.signals import ControlSignals, goal_pressure
from lolm.control.receipt import build_control_receipt
from lolm.control.memory_snapshot import snapshot_stats

TICK_TRIGGERS = (
    "scheduled_tick", "manual_tick", "post_answer_tick",
    "memory_consolidation_tick", "goal_review_tick", "uncertainty_review_tick",
)


@dataclass
class TickInput:
    agentId: str
    trigger: str = "scheduled_tick"
    liveStats: Dict[str, Any] = field(default_factory=dict)
    contextSignals: Dict[str, Any] = field(default_factory=dict)


def _signals_from_state(state: AgentState, goals: List[Dict[str, Any]],
                        extra: Dict[str, Any]) -> ControlSignals:
    base = {
        "surfaceUncertainty": state.unresolvedUncertainty,
        "latentUncertainty": state.unresolvedUncertainty,
        "drift": state.accumulatedDrift,
        "contradictionRisk": state.contradictionRisk,
        "memoryPressure": state.memoryPressure,
        "verificationNeed": state.verificationPressure,
        "toolNeed": state.toolPressure,
        "novelty": state.noveltyPressure,
        "goalPressure": max(state.goalPressure, goal_pressure(goals)),
        "safetyRisk": (state.safetyState or {}).get("risk", 0.0),
    }
    base.update(extra or {})
    return ControlSignals.from_dict(base)


def autonomy_tick(
    inp: TickInput,
    *,
    memory_fn: Optional[Callable[[AgentState], Dict[str, Any]]] = None,
    goals_fn: Optional[Callable[[AgentState], List[Dict[str, Any]]]] = None,
    signals_fn: Optional[Callable[..., ControlSignals]] = None,
    execute_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    tool_executor: Optional[Any] = None,
    tool_router: Optional[Callable[..., tuple]] = None,
    field_state: Optional[NFETField] = None,
    base_dir: Optional[Any] = None,
    autonomy_level: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one tick. Returns {decision, observation, receipt, state}."""
    state = load_agent_state(inp.agentId, base_dir)
    state.now = _now_iso()
    state.runId = f"tick-{uuid.uuid4().hex[:12]}"

    live_stats = (memory_fn(state) if memory_fn else None) or inp.liveStats or {}
    snap = snapshot_stats(live_stats, scope=(state.memoryState or {}).get("scope", "shared_demo"))
    goals = (goals_fn(state) if goals_fn else None) or state.activeGoals

    if signals_fn:
        sig = signals_fn(state=state, goals=goals, trigger=inp.trigger)
    else:
        sig = _signals_from_state(state, goals, inp.contextSignals)

    decision = decide(sig, state=state.to_dict(), field=field_state,
                      input_type=inp.trigger, run_id=state.runId)

    # Honest autonomy level: L4 only when a tool executor is actually wired.
    level = autonomy_level or ("L4_TOOL_USING_AUTONOMY" if tool_executor is not None
                               else "L3_MEMORY_GOAL_TICKS")

    # Execute the chosen action. With a tool executor, a triggering action that
    # maps to a tool is RUN — gated again by the calibrated gate inside the
    # executor and outcome-verified. Otherwise it is recorded as indicated-but-
    # not-executed. Money/send/delete/deploy can never run here (hard human-gate).
    observation: Dict[str, Any] = {"executed": False, "detail": None}
    actions: List[Dict[str, Any]] = []
    tools_used: List[Dict[str, Any]] = []
    if decision.actionTriggered:
        rec = None
        if tool_executor is not None:
            router = tool_router or _default_tool_router
            tname, targs = router(decision, state, inp)
            if tname:
                rec = tool_executor.run(tname, targs, decision.fusedUncertainty,
                                        risk_profiles=(inp.contextSignals or {}).get("riskProfiles"))
        if rec is not None:
            observation = {"executed": rec.get("executed"), "detail": rec.get("detail"),
                           "outcome": rec.get("outcome"), "output": rec.get("output")}
            tools_used.append({"name": rec.get("tool"), "reason": decision.reason,
                               "resultHash": _short_hash(rec.get("output"))})
            actions.append({
                "type": decision.selectedAction, "triggered": True,
                "allowed": decision.actionAllowed, "executed": bool(rec.get("executed")),
                "tool": rec.get("tool"), "resultSummary": rec.get("detail"),
                "blockedReason": None if rec.get("executed") else rec.get("outcome"),
            })
        elif execute_fn is not None:
            observation = execute_fn(decision=decision, state=state) or observation
            actions.append({
                "type": decision.selectedAction, "triggered": True,
                "allowed": decision.actionAllowed, "executed": bool(observation.get("executed")),
                "resultSummary": observation.get("detail"),
                "blockedReason": None if observation.get("executed") else observation.get("error"),
            })
        else:
            actions.append({
                "type": decision.selectedAction, "triggered": True,
                "allowed": decision.actionAllowed, "executed": False,
                "blockedReason": "no runner wired — indicated but not executed",
            })
    else:
        actions.append({"type": decision.selectedAction, "triggered": False,
                        "allowed": decision.actionAllowed, "executed": False})

    receipt = build_control_receipt(
        decision, memory_snapshot=snap, autonomy_level=level,
        input_type=inp.trigger, trigger_reason=inp.trigger, actions=actions,
        tools_used=tools_used or None, previous_receipt_hash=state.lastReceiptHash,
    )
    autonomy_level = level

    state.lastDecision = decision.to_dict()
    state.lastReceiptHash = receipt["receiptHash"]
    state.ticksRun += 1
    state.autonomyLevel = autonomy_level
    persist_agent_state(state, base_dir)

    return {"decision": decision.to_dict(), "observation": observation,
            "receipt": dict(receipt), "state": state.to_dict()}


def _default_tool_router(decision: Any, state: AgentState, inp: TickInput) -> tuple:
    """Map a controller action to a (tool_name, args). Unknown -> (None, {})."""
    ctx = inp.contextSignals or {}
    act = decision.selectedAction
    if act == "run_tool":
        return ctx.get("tool"), (ctx.get("toolArgs") or {})
    if act in ("recall", "retrieve"):
        return "recall", {"query": ctx.get("query") or state.lastUserTurn or ""}
    if act == "verify":
        if ctx.get("expr"):
            return "calc", {"expr": ctx["expr"]}
        return "recall", {"query": ctx.get("query") or state.lastUserTurn or ""}
    return None, {}


def _short_hash(obj: Any) -> str:
    import hashlib
    import json as _json
    try:
        s = _json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
