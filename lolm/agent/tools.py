# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Safe tool layer for autonomous ticks — real execution, gated + verified (L4).

Tools the agent may run ON ITS OWN are READ-ONLY or REVERSIBLE only. Every call
is gated by the calibrated autonomy gate (measured uncertainty + risk tier) and
its real-world outcome is independently VERIFIED before any receipt may say it
happened. Money / send / delete / deploy are never in this registry — they stay
hard-gated to a human no matter how confident the controller is. That asymmetry
is what makes tool-using autonomy safe to ship.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from lolm.autonomy import AutonomyGate


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    detail: str = ""


class Tool:
    name: str = "tool"
    action_kind: str = "read"        # read | reversible (never irreversible here)
    description: str = ""

    def run(self, args: Dict[str, Any]) -> ToolResult:  # pragma: no cover - interface
        raise NotImplementedError

    def verify(self, args: Dict[str, Any], result: ToolResult) -> bool:
        """Independently confirm the outcome. Default: success is the signal."""
        return bool(result.ok)


class ClockTool(Tool):
    name, action_kind, description = "clock", "read", "read the current UTC time"

    def __init__(self, now_fn: Optional[Callable[[], str]] = None):
        self.now_fn = now_fn or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def run(self, args):
        return ToolResult(True, self.now_fn(), "read clock")

    def verify(self, args, result):
        return bool(result.output) and "T" in str(result.output)


class CalcTool(Tool):
    name, action_kind, description = "calc", "read", "evaluate an arithmetic expression"

    def run(self, args):
        from lolm.verifiers import _tokenize, _evaluate
        expr = str(args.get("expr", ""))
        toks = _tokenize(expr)
        if toks is None:
            return ToolResult(False, None, f"unparseable: {expr!r}")
        val = _evaluate(toks)
        return ToolResult(val is not None, val, f"{expr} = {val}")

    def verify(self, args, result):
        # Recompute from scratch — the outcome check must not trust the run.
        from lolm.verifiers import _tokenize, _evaluate
        toks = _tokenize(str(args.get("expr", "")))
        return toks is not None and _evaluate(toks) == result.output


class RecallTool(Tool):
    name, action_kind, description = "recall", "read", "recall memories for a query"

    def __init__(self, recall_fn: Callable[[str], List[Any]]):
        self.recall_fn = recall_fn

    def run(self, args):
        hits = self.recall_fn(str(args.get("query", ""))) or []
        return ToolResult(True, hits, f"recalled {len(hits)} item(s)")

    def verify(self, args, result):
        return isinstance(result.output, list)


class GoalProgressTool(Tool):
    name, action_kind, description = "goal_progress", "reversible", "advance a goal's progress"

    def __init__(self, update_fn: Callable[[str, float], bool]):
        self.update_fn = update_fn

    def run(self, args):
        ok = bool(self.update_fn(str(args.get("goalId", "")), float(args.get("progress", 0.0))))
        return ToolResult(ok, {"goalId": args.get("goalId"), "progress": args.get("progress")},
                          "updated goal progress" if ok else "goal not found")


@dataclass
class ToolExecutor:
    """Runs a named tool only if the gate approves, then verifies the outcome."""

    gate: AutonomyGate
    tools: Dict[str, Tool] = field(default_factory=dict)
    require_human: Optional[frozenset] = None   # None -> HARD_HUMAN_GATE default

    @classmethod
    def of(cls, gate: AutonomyGate, tools: List[Tool],
           require_human: Optional[frozenset] = None) -> "ToolExecutor":
        return cls(gate=gate, tools={t.name: t for t in tools}, require_human=require_human)

    def names(self) -> List[str]:
        return sorted(self.tools)

    def run(self, name: str, args: Optional[Dict[str, Any]], uncertainty: float,
            risk_profiles: Optional[List[str]] = None) -> Dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {"tool": name, "executed": False, "outcome": "unknown_tool",
                    "detail": f"no such tool: {name}", "decision": None}
        kwargs = {} if self.require_human is None else {"require_human": self.require_human}
        d = self.gate.gate_action(uncertainty, tool.action_kind, risk_profiles or [], **kwargs)
        rec: Dict[str, Any] = {"tool": name, "action_kind": tool.action_kind,
                               "decision": d.to_dict(), "executed": False,
                               "outcome": d.mode, "detail": d.reason}
        if d.mode != "act":
            return rec   # gather / escalate -> not executed; recorded honestly
        try:
            result = tool.run(args or {})
        except Exception as exc:
            rec.update(executed=False, outcome="error", detail=f"tool error: {exc}"[:200])
            return rec
        try:
            verified = bool(tool.verify(args or {}, result))
        except Exception:
            verified = False
        rec.update(executed=True,
                   outcome=("verified" if (result.ok and verified) else "failed"),
                   detail=result.detail, output=result.output)
        return rec
