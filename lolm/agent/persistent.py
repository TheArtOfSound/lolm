# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The bounded persistent agent (L5) — maintain everything, under limits.

A persistent agent is not one that never stops; it is one that keeps coherent
state and acts only within bounds. ``PersistentAgent.run`` drives a sequence of
autonomy ticks that together maintain GOALS, MEMORY (consolidation), VERIFICATION,
SCHEDULING, NUDGING, and TOOL USE — each tick gated by the calibrated controller,
each tool call outcome-verified, every step receipt-chained — and it STOPS when a
budget is spent, a safety limit is crossed, or the controller converges to idle
(restraint). Money/send/delete/deploy stay hard-gated to a human throughout.

That is the honest content of L5_BOUNDED_PERSISTENT_AGENT: all the subsystems,
bounded and provable, not an always-on illusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from lolm.agent.agent_state import AgentState, load_agent_state
from lolm.agent.autonomy_tick import autonomy_tick, TickInput
from lolm.control.memory_consolidation import decide_memory_write

# A persistent run rotates through these review triggers unless given a plan.
DEFAULT_CYCLE = ("goal_review_tick", "uncertainty_review_tick",
                 "memory_consolidation_tick", "scheduled_tick")


@dataclass
class Budget:
    maxActions: int = 6          # triggering actions across the whole run
    maxToolCalls: int = 4        # real tool executions across the whole run
    maxCostUsd: float = 0.0      # safe tools are free; > 0 reserved for paid tools


@dataclass
class PersistentAgent:
    agent_id: str
    tool_executor: Optional[Any] = None
    goals_fn: Optional[Callable[[AgentState], List[Dict[str, Any]]]] = None
    memory_candidates_fn: Optional[Callable[[AgentState], List[Dict[str, Any]]]] = None
    memory_write_fn: Optional[Callable[[Dict[str, Any]], None]] = None
    scheduler: Optional[Any] = None
    base_dir: Optional[Any] = None

    def _cycle(self, n: int, plan: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if plan:
            return plan
        return [{"trigger": DEFAULT_CYCLE[i % len(DEFAULT_CYCLE)]} for i in range(n)]

    def run(self, *, max_ticks: int = 8, budget: Optional[Budget] = None,
            safety_limit: float = 0.8, plan: Optional[List[Dict[str, Any]]] = None,
            idle_converge: int = 2,
            autonomy_level: str = "L5_BOUNDED_PERSISTENT_AGENT") -> Dict[str, Any]:
        budget = budget or Budget()
        specs = self._cycle(max_ticks, plan)
        receipts: List[Dict[str, Any]] = []
        ticks: List[Dict[str, Any]] = []
        tools_used: List[Dict[str, Any]] = []
        consolidations: List[Dict[str, Any]] = []
        scheduled: List[str] = []
        actions_used = 0
        tool_calls = 0
        idle_streak = 0
        stopped = "max_ticks"

        for spec in specs[:max_ticks]:
            st = load_agent_state(self.agent_id, self.base_dir)
            if (st.safetyState or {}).get("risk", 0.0) >= safety_limit:
                stopped = "safety_limit"
                break
            if actions_used >= budget.maxActions:
                stopped = "budget_actions"
                break

            allow_tools = self.tool_executor if tool_calls < budget.maxToolCalls else None
            inp = TickInput(self.agent_id, spec.get("trigger", "scheduled_tick"),
                            liveStats=spec.get("liveStats", {}),
                            contextSignals=spec.get("context", {}))
            out = autonomy_tick(inp, tool_executor=allow_tools, goals_fn=self.goals_fn,
                                signals_fn=spec.get("signals_fn"),
                                base_dir=self.base_dir, autonomy_level=autonomy_level)
            ticks.append(out)
            receipts.append(out["receipt"])
            d = out["decision"]

            if d["actionTriggered"]:
                actions_used += 1
                idle_streak = 0
                used = out["receipt"].get("toolsUsed") or []
                if used:
                    tool_calls += len(used)
                    tools_used.extend(used)
                if d["selectedAction"] == "schedule" and self.scheduler is not None:
                    sid = self.scheduler.schedule(
                        self.agent_id, "scheduled_tick",
                        run_after_ms=spec.get("delayMs", 60_000.0), reason=d["reason"])
                    scheduled.append(sid)
            else:
                idle_streak += 1

            # Memory-consolidation subsystem (its own bounded pass).
            if spec.get("trigger") == "memory_consolidation_tick" and self.memory_candidates_fn:
                for cand in (self.memory_candidates_fn(st) or []):
                    dec = decide_memory_write(cand, scope=(st.memoryState or {}).get("scope", "shared_demo"))
                    consolidations.append(dec)
                    if dec["written"] and self.memory_write_fn is not None:
                        try:
                            self.memory_write_fn(dec)
                        except Exception:
                            pass

            if idle_streak >= idle_converge:
                stopped = "converged_idle"
                break

        final = load_agent_state(self.agent_id, self.base_dir).to_dict()
        return {
            "agentId": self.agent_id,
            "autonomyLevel": autonomy_level,
            "ticks": len(ticks),
            "actionsUsed": actions_used,
            "toolCalls": tool_calls,
            "toolsUsed": tools_used,
            "consolidations": consolidations,
            "scheduled": scheduled,
            "stoppedBy": stopped,
            "budget": {"maxActions": budget.maxActions, "maxToolCalls": budget.maxToolCalls},
            "receiptChain": [r["receiptHash"] for r in receipts],
            "receipts": receipts,
            "finalState": final,
        }
