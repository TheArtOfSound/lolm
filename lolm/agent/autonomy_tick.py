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
    field_state: Optional[NFETField] = None,
    base_dir: Optional[Any] = None,
    autonomy_level: str = "L3_MEMORY_GOAL_TICKS",
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

    # Execute only what is allowed and only if a runner is provided; otherwise the
    # action is honestly recorded as indicated-but-not-executed.
    observation: Dict[str, Any] = {"executed": False, "detail": None}
    actions: List[Dict[str, Any]] = []
    if decision.actionTriggered:
        if execute_fn is not None:
            observation = execute_fn(decision=decision, state=state) or observation
        actions.append({
            "type": decision.selectedAction,
            "triggered": True,
            "allowed": decision.actionAllowed,
            "executed": bool(observation.get("executed")),
            "resultSummary": observation.get("detail"),
            "blockedReason": None if observation.get("executed") else
                             ("no runner wired — indicated but not executed"
                              if execute_fn is None else observation.get("error")),
        })
    else:
        actions.append({"type": decision.selectedAction, "triggered": False,
                        "allowed": decision.actionAllowed, "executed": False})

    receipt = build_control_receipt(
        decision, memory_snapshot=snap, autonomy_level=autonomy_level,
        input_type=inp.trigger, trigger_reason=inp.trigger, actions=actions,
        previous_receipt_hash=state.lastReceiptHash,
    )

    state.lastDecision = decision.to_dict()
    state.lastReceiptHash = receipt["receiptHash"]
    state.ticksRun += 1
    state.autonomyLevel = autonomy_level
    persist_agent_state(state, base_dir)

    return {"decision": decision.to_dict(), "observation": observation,
            "receipt": dict(receipt), "state": state.to_dict()}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
