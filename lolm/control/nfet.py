# Copyright (c) 2026 Qira LLC. All rights reserved.
"""NFET event-field control — fused uncertainty, rolling z-spikes, action choice.

This is the controller. ``decide`` turns a ControlSignals vector into a
DecisionPacket by:

  1. fused uncertainty  U_total = σ(Σ w·signal + b)
  2. event-field energy E = Σ α·spike − α_cost·cost − α_safe·safety,
     where spike_x = max(0, z_x − κ) over rolling stats (a prior baseline seeds
     a cold controller so a clearly elevated signal still reacts).
  3. a safety override (refuse) and an idle gate (restraint is a real decision).
  4. action scoring: each candidate's score is driven by its specific pressure;
     the argmax above its threshold, bounded by safety + budget, wins. If none
     clears its bar, the controller idles (tick) or answers (prompt).

NFET is not a label here. The chosen action is a function of these numbers, and
the numbers go into the receipt.
"""

from __future__ import annotations

import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from lolm.control.config import (
    NFET_WEIGHTS, NFET_FIELD_WEIGHTS, NFET_THRESHOLDS, ACTION_SCORE_WEIGHTS,
    FIELD_KAPPA, PRIOR_MEAN, PRIOR_STD, EPS,
)
from lolm.control.signals import ControlSignals, fused_uncertainty
from lolm.control.decision_packet import DecisionPacket, CandidateScore

AGENT_ACTIONS = (
    "answer", "continue", "recall", "retrieve", "verify", "branch", "revise",
    "run_tool", "schedule", "nudge", "idle", "refuse",
)
# Actions that count as the controller TAKING an action (vs answering/idling).
_TRIGGERING = {"recall", "retrieve", "verify", "branch", "revise", "run_tool",
               "schedule", "nudge"}

# Which field signals feed the event-field energy (positive contributors).
_FIELD_SIGNALS = ("uncertainty", "drift", "contradiction", "memoryPressure",
                  "goalPressure", "verificationNeed", "toolNeed")


class _RollingStat:
    """Rolling mean/std with a prior baseline so cold z-scores still react."""

    def __init__(self, window: int = 64):
        self.vals: deque = deque(maxlen=window)

    def push(self, x: float) -> None:
        if x is not None and not math.isnan(x) and not math.isinf(x):
            self.vals.append(float(x))

    def z(self, x: float) -> float:
        if len(self.vals) >= 4:
            mu = sum(self.vals) / len(self.vals)
            var = sum((v - mu) ** 2 for v in self.vals) / (len(self.vals) - 1)
            sd = max(math.sqrt(max(var, 0.0)), PRIOR_STD * 0.5)
        else:
            mu, sd = PRIOR_MEAN, PRIOR_STD
        return (x - mu) / max(sd, EPS)


class NFETField:
    """Holds rolling stats across runs/ticks and computes event-field energy."""

    def __init__(self):
        self.stats: Dict[str, _RollingStat] = {s: _RollingStat() for s in _FIELD_SIGNALS}

    def _values(self, sig: ControlSignals, u_total: float) -> Dict[str, float]:
        return {
            "uncertainty": u_total,
            "drift": sig.drift,
            "contradiction": sig.contradictionRisk,
            "memoryPressure": sig.memoryPressure,
            "goalPressure": sig.goalPressure,
            "verificationNeed": sig.verificationNeed,
            "toolNeed": sig.toolNeed,
        }

    def observe(self, sig: ControlSignals, u_total: float) -> None:
        for k, v in self._values(sig, u_total).items():
            self.stats[k].push(v)

    def energy(self, sig: ControlSignals, u_total: float) -> Dict[str, Any]:
        vals = self._values(sig, u_total)
        a = NFET_FIELD_WEIGHTS
        spikes: Dict[str, Dict[str, float]] = {}
        e = 0.0
        for k, v in vals.items():
            z = self.stats[k].z(v)
            spike = max(0.0, z - FIELD_KAPPA)
            spikes[k] = {"value": round(v, 4), "z": round(z, 3), "spike": round(spike, 4)}
            e += a[k] * spike
        e -= a["costPressure"] * sig.costPressure
        e -= a["safetyRisk"] * sig.safetyRisk
        dominant = sorted(
            ({"signal": k, **d} for k, d in spikes.items() if d["spike"] > 0),
            key=lambda d: d["spike"], reverse=True,
        )
        return {"energy": e, "spikes": spikes, "dominant": dominant}


def _score_actions(sig: ControlSignals, u: float) -> Dict[str, float]:
    """Per-action score (0..1-ish). Each is driven by its specific pressure."""
    mem_gap = 1.0 - sig.memoryRelevance
    return {
        "verify":   0.5 * sig.verificationNeed + 0.3 * u + 0.2 * sig.contradictionRisk,
        "retrieve": 0.5 * sig.retrievalNeed + 0.3 * mem_gap + 0.2 * u,
        "recall":   0.4 * sig.memoryPressure + 0.3 * mem_gap + 0.3 * sig.retrievalNeed,
        "branch":   0.5 * sig.branchNeed + 0.3 * sig.drift + 0.2 * u,
        "revise":   0.4 * sig.drift + 0.3 * sig.contradictionRisk + 0.3 * u,
        "run_tool": 0.5 * sig.toolNeed + 0.3 * u + 0.2 * sig.goalPressure,
        "schedule": 0.5 * sig.goalPressure + 0.3 * sig.urgency - 0.2 * u,
        "nudge":    sig.userInterruptValue,
    }


_ACTION_THRESHOLD_KEY = {
    "verify": "verify", "retrieve": "retrieve", "recall": "retrieve",
    "branch": "branch", "revise": "act", "run_tool": "act",
    "schedule": "act", "nudge": "nudge",
}


def decide(signals: Any, state: Optional[Dict[str, Any]] = None,
           field: Optional[NFETField] = None, input_type: str = "scheduled_tick",
           run_id: Optional[str] = None, tick_id: Optional[str] = None,
           now: Optional[str] = None) -> DecisionPacket:
    """Score the signals and choose an action. Returns a DecisionPacket."""
    sig = signals if isinstance(signals, ControlSignals) else ControlSignals.from_dict(signals)
    state = state or {}
    field = field or NFETField()
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    now = now or _now_iso()

    u = fused_uncertainty(sig)
    fe = field.energy(sig, u)
    energy = fe["energy"]
    T = NFET_THRESHOLDS
    is_prompt = input_type in ("user_prompt",)

    budget = (state.get("budgetState") or {})
    actions_left = budget.get("maxActionsPerTick", 99)
    spent_actions = budget.get("usedActionsThisTick", 0)
    over_budget = spent_actions >= actions_left

    scores = _score_actions(sig, u)
    candidates: List[CandidateScore] = []
    for action, sc in scores.items():
        thr = T[_ACTION_THRESHOLD_KEY[action]]
        allowed = True
        blocked = None
        if over_budget and action in _TRIGGERING:
            allowed, blocked = False, "action budget exhausted"
        if action == "nudge":
            cooldown_ok = state.get("nudgeCooldownElapsed", True)
            if sig.goalPressure < 0.5 or not cooldown_ok or sig.safetyRisk >= 0.5:
                allowed = allowed and False
                blocked = blocked or "nudge gate (goal/cooldown/safety) not met"
        eligible = (sc > thr) and allowed
        candidates.append(CandidateScore(action, sc, allowed, thr, eligible, blocked))

    sources: List[str] = ["nfet"]
    for d in fe["dominant"][:3]:
        sources.append(d["signal"] if d["signal"] != "uncertainty" else "surface")

    # 1) Safety override.
    if sig.safetyRisk >= T["refuseSafety"]:
        return _packet("refuse", sig, u, energy, fe, candidates, False, False,
                       f"safety risk {sig.safetyRisk:.2f} ≥ refuse threshold "
                       f"{T['refuseSafety']:.2f} — refuse and do not act",
                       sources + ["safety"], run_id, tick_id, now, input_type)

    # 2) Idle gate for ticks (restraint is a first-class decision).
    if not is_prompt and energy < T["idle"]:
        return _packet("idle", sig, u, energy, fe, candidates, True, False,
                       f"event-field energy {energy:.3f} < idle threshold "
                       f"{T['idle']:.2f} — no pressure justifies action",
                       sources, run_id, tick_id, now, input_type)

    # 3) Pick the best eligible triggering action.
    eligible = [c for c in candidates if c.eligible]
    if eligible:
        best = max(eligible, key=lambda c: c.score)
        return _packet(best.action, sig, u, energy, fe, candidates, True, True,
                       f"{best.action} scored {best.score:.3f} > its threshold "
                       f"{best.threshold:.2f} and won the action argmax",
                       _sources_for(best.action, sources), run_id, tick_id, now, input_type)

    # 4) Nothing crossed a bar: answer (prompt) or idle (tick).
    if is_prompt:
        return _packet("answer", sig, u, energy, fe, candidates, True, False,
                       "no controller action crossed its threshold — answer directly",
                       sources, run_id, tick_id, now, input_type)
    return _packet("idle", sig, u, energy, fe, candidates, True, False,
                   "no candidate action crossed its threshold — idle",
                   sources, run_id, tick_id, now, input_type)


def _sources_for(action: str, base: List[str]) -> List[str]:
    extra = {
        "verify": ["verification"], "retrieve": ["retrieval", "memory"],
        "recall": ["memory"], "branch": ["drift", "contradiction"],
        "revise": ["drift"], "run_tool": ["tool"], "schedule": ["goal"],
        "nudge": ["goal"],
    }.get(action, [])
    out = list(base)
    for s in extra:
        if s not in out:
            out.append(s)
    return out


def _packet(action, sig, u, energy, fe, candidates, allowed, triggered, reason,
            sources, run_id, tick_id, now, input_type) -> DecisionPacket:
    return DecisionPacket(
        id=f"dp-{uuid.uuid4().hex[:12]}", runId=run_id, tickId=tick_id,
        createdAt=now, inputType=input_type, mode=action, selectedAction=action,
        candidateActions=candidates, signals=sig, fieldEnergy=energy,
        fusedUncertainty=u, confidence=round(1.0 - u, 4), thresholds=dict(NFET_THRESHOLDS),
        weights={"fusion": dict(NFET_WEIGHTS), "field": dict(NFET_FIELD_WEIGHTS),
                 "action": dict(ACTION_SCORE_WEIGHTS)},
        dominantSpikes=fe["dominant"], actionAllowed=allowed, actionTriggered=triggered,
        reason=reason, decisionSources=sources,
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
