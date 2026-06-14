# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The autonomous operator loop — plan -> gate -> act -> verify -> re-measure.

This is where the spine becomes an agent. Given a goal, it repeatedly:

  1. PLAN     — the planner proposes the next tool call (or finishes).
  2. MEASURE  — the run's MEASURED uncertainty for that step (graft telemetry).
  3. GATE     — lolm.autonomy decides ACT / GATHER / ESCALATE for the action's
                risk tier and the calibrated P(correct).
  4. ACT      — only if ACT: run the tool through the Operator, which VERIFIES
                the real-world outcome (action -> observation -> outcome).
  5. RE-MEASURE — feed the verified observation back; GATHER re-plans with more
                evidence; ESCALATE stops and hands a prepared action to a human.

Every step is an auditable record; every executed action's (uncertainty,
verified-outcome) pair feeds the flywheel, so the operator earns autonomy on the
tasks it proves reliable at. The planner is injected (testable with a
deterministic stub); a frontier-backed planner lives in operator_planner.py.

Safety is structural, not advisory: the loop NEVER executes a tool the gate did
not approve, and the Operator hard-gates money/send/delete/deploy to a human no
matter how confident the planner is.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from local_ui.operator import Operator

# A planner returns either:
#   {"action": "tool",   "tool": "...", "args": {...}, "reason": "...",
#    "risk_profiles": [...]}                      # take a tool action
#   {"action": "finish", "answer": "..."}         # done
Planner = Callable[[str, List[Dict[str, Any]]], Dict[str, Any]]
UncertaintyFn = Callable[[str], float]


@dataclass
class OperatorAgent:
    operator: Operator
    planner: Planner
    flywheel: Optional[Any] = None
    uncertainty_fn: UncertaintyFn = lambda _text: 0.0
    max_steps: int = 8

    def run(self, goal: str, risk_profiles: Optional[List[str]] = None,
            max_steps: Optional[int] = None) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        history: List[Dict[str, Any]] = []
        ended = "step_budget"
        answer: Optional[str] = None
        limit = max_steps or self.max_steps

        for n in range(1, limit + 1):
            plan = self.planner(goal, history) or {}
            action = plan.get("action")

            if action == "finish":
                answer = plan.get("answer")
                ended = "finished"
                steps.append({"n": n, "plan": plan, "record": None})
                break

            if action != "tool" or not plan.get("tool"):
                # Malformed plan — stop honestly rather than guess.
                ended = "planner_error"
                steps.append({"n": n, "plan": plan, "record": None,
                              "note": "planner did not return a valid tool action"})
                break

            tool = str(plan["tool"])
            args = plan.get("args") or {}
            rps = plan.get("risk_profiles") or risk_profiles or []
            uncertainty = float(self.uncertainty_fn(plan.get("reason") or json.dumps(plan)))

            try:
                rec = self.operator.attempt(tool, args, uncertainty, rps)
            except KeyError:
                ended = "unknown_tool"
                steps.append({"n": n, "plan": plan, "record": None,
                              "note": f"unknown tool: {tool}"})
                break

            rd = rec.to_dict()
            steps.append({"n": n, "plan": plan, "record": rd})
            history.append({
                "tool": tool, "args": args, "decision": rd["decision"]["mode"],
                "outcome": rec.outcome,
                "observation": (rec.observation or {}).get("detail"),
            })

            # Flywheel: a tool action's verified/failed outcome is a correctness
            # signal for the gate's decision to act at this uncertainty.
            if (self.flywheel is not None and rec.executed
                    and rec.outcome in ("verified", "failed")):
                self.flywheel.record(uncertainty, rec.outcome == "verified",
                                     meta={"tool": tool})

            if rec.outcome == "escalate":
                ended = "escalated_to_human"
                break
            # "gather"/"failed"/"verified" -> loop; the planner re-plans with the
            # new observation (or decides to finish).

        return {
            "goal": goal,
            "steps": steps,
            "n_steps": len(steps),
            "ended": ended,
            "answer": answer,
            "escalation": _pending_escalation(steps) if ended == "escalated_to_human" else None,
        }


def _pending_escalation(steps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The prepared action awaiting a human, with the agent's calibrated reason."""
    last = steps[-1] if steps else None
    if not last or not last.get("record"):
        return None
    rec = last["record"]
    return {
        "tool": rec["tool"], "args": rec["args"],
        "decision": rec["decision"],
        "preview": "prepared but NOT executed — a human must approve",
    }
