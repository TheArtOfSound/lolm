# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Persistent agent state — LOLM cannot be a persistent agent without it.

JSON-persisted per agent. Carries the bounded pressures the controller reads
between prompts (unresolved uncertainty, drift, goal pressure, …), the active
goals and open questions, and the autonomy level the system has ACTUALLY reached
(never claimed higher than implemented).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


class AutonomyLevel:
    L0 = "L0_REACTIVE_ONLY"
    L1 = "L1_RECEIPT_MONITORED"
    L2 = "L2_CONTROLLER_ACTIONS"
    L3 = "L3_MEMORY_GOAL_TICKS"
    L4 = "L4_TOOL_USING_AUTONOMY"
    L5 = "L5_BOUNDED_PERSISTENT_AGENT"
    ORDER = [L0, L1, L2, L3, L4, L5]


def compute_autonomy_level(caps: Dict[str, bool]) -> str:
    """Honest level from real capabilities — never claim more than is wired.

    caps keys: receipts, controller_actions, memory_goal_ticks, tools, bounded_persistent.
    """
    level = AutonomyLevel.L0
    if caps.get("receipts"):
        level = AutonomyLevel.L1
    if caps.get("controller_actions"):
        level = AutonomyLevel.L2
    if caps.get("memory_goal_ticks"):
        level = AutonomyLevel.L3
    if caps.get("tools") and caps.get("memory_goal_ticks"):
        level = AutonomyLevel.L4
    if caps.get("bounded_persistent") and caps.get("tools"):
        level = AutonomyLevel.L5
    return level


@dataclass
class AgentState:
    agentId: str
    runId: str = ""
    conversationId: Optional[str] = None
    now: str = ""

    activeGoals: List[Dict[str, Any]] = field(default_factory=list)
    openQuestions: List[Dict[str, Any]] = field(default_factory=list)
    memoryState: Dict[str, Any] = field(default_factory=dict)
    toolState: Dict[str, Any] = field(default_factory=lambda: {
        "availableTools": [], "allowedTools": [], "blockedTools": [], "lastToolCalls": []})
    budgetState: Dict[str, Any] = field(default_factory=lambda: {"maxActionsPerTick": 3})
    safetyState: Dict[str, Any] = field(default_factory=lambda: {"risk": 0.0, "blocked": False})

    lastUserTurn: Optional[str] = None
    lastAssistantTurn: Optional[str] = None
    currentDraft: Optional[str] = None

    unresolvedUncertainty: float = 0.0
    accumulatedDrift: float = 0.0
    contradictionRisk: float = 0.0
    noveltyPressure: float = 0.0
    goalPressure: float = 0.0
    memoryPressure: float = 0.0
    verificationPressure: float = 0.0
    toolPressure: float = 0.0

    autonomyLevel: str = AutonomyLevel.L2
    lastDecision: Optional[Dict[str, Any]] = None
    lastReceiptHash: Optional[str] = None
    ticksRun: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _state_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runs" / "agent_state"


def load_agent_state(agent_id: str, base_dir: Optional[Path] = None) -> AgentState:
    path = (Path(base_dir) if base_dir else _state_dir()) / f"{agent_id}.json"
    try:
        data = json.loads(path.read_text())
        known = {f for f in AgentState.__dataclass_fields__}
        return AgentState(**{k: v for k, v in data.items() if k in known})
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return AgentState(agentId=agent_id, now=_now_iso(),
                          runId=f"run-{uuid.uuid4().hex[:12]}")


def persist_agent_state(state: AgentState, base_dir: Optional[Path] = None) -> None:
    d = Path(base_dir) if base_dir else _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{state.agentId}.json").write_text(json.dumps(state.to_dict(), indent=2))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
