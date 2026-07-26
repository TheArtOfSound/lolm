# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Claude is the brain; LOLM's control loop is the harness.

The original NFET loop used the 0.6B local model as the *reasoner*, which is
why a quality lift over baseline was never provable — the brain was weak. This
module inverts that: **Claude does the reasoning, and LOLM's discipline layer
wraps it** — uncertainty gating (lolm.autonomy), deterministic verifiers
(lolm.verifiers), risk profiling (lolm.critique), a hash-chained receipt
(lolm.run_receipt), and the verified-outcome flywheel (lolm.flywheel). The
weak model is *demoted*, not deleted: it becomes an INDEPENDENT OBSERVER of
Claude's output (lolm telemetry re-read over Claude's text), giving a second,
uncorrelated uncertainty estimate. When the observer is more alarmed than
Claude's own self-report, that disagreement is itself a verify trigger — a
signal neither model produces alone.

Two uncertainty signals, fused into the one scalar U the gate consumes:

    u_self  = invert(self_confidence)        # Claude's own P(correct), in U-units
    u_nfet  = aggregate_uncertainty(frames)  # the independent observer, same z-scale
    u_fused = max(u_self, u_nfet) + 0.5 * max(0, u_nfet - u_self)
              #     conservative floor      +  lean toward the alarmed observer

``u_self`` and ``u_nfet`` are in the SAME domain on purpose: ``u_nfet`` is a
z-scored entropy/drift aggregate, and ``u_self`` is the inverse of the gate's
own logistic prior, so feeding either back through the prior round-trips. The
calibrator is then fit on ``(u_fused, verified_outcome)`` — so autonomy is
earned against the fused signal Claude actually acts on.

Pure-Python except for the optional telemetry pass, which only runs when a
local backbone+graft is loaded. With no model, ``frames=[]`` and the gate
honestly treats "no telemetry" as a blind spot, not as confidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lolm.autonomy import AutonomyGate, HARD_HUMAN_GATE, classify_action_risk
from lolm.calibration import aggregate_uncertainty
from lolm.critique import assess as critique_assess, risk_profile
from lolm.flywheel import AutonomyFlywheel
from lolm.run_receipt import build_receipt, check_contract, parse_contract
from lolm.verifiers import run_text_verifiers

# Keep Claude's track record SEPARATE from the NFET-controller showcase
# flywheel (runs/autonomy_flywheel.jsonl) — mixing them would pollute both
# calibrations (the controller's pollution incident is documented in memory).
REPO_ROOT = Path(__file__).resolve().parent.parent
FLYWHEEL_PATH = REPO_ROOT / "runs" / "claude_autonomy_flywheel.jsonl"
LEDGER_PATH = REPO_ROOT / "runs" / "claude_receipts.jsonl"

_LEDGER_LOCK = threading.Lock()
_FLYWHEEL: Optional[AutonomyFlywheel] = None


def flywheel() -> AutonomyFlywheel:
    global _FLYWHEEL
    if _FLYWHEEL is None:
        _FLYWHEEL = AutonomyFlywheel(FLYWHEEL_PATH)
    return _FLYWHEEL


# --- the two uncertainty signals -------------------------------------------

def invert_p_correct(p: float) -> float:
    """Map a self-reported P(correct) back into the gate's U domain.

    Exact inverse of ``calibration._default_p_correct`` (logistic centred so
    U~0 -> 0.8, U=0.5 -> 0.5, U>=2 -> <0.3). Feeding the result back through
    the prior reproduces ``p``, so Claude's verbalized confidence enters the
    same scale as the NFET observer's entropy aggregate.
    """
    p = min(max(float(p), 1e-4), 1.0 - 1e-4)
    return 0.5 + math.log(1.0 / p - 1.0) / 1.4


def fuse_uncertainty(self_confidence: float,
                     nfet_frames: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Fuse Claude's self-confidence with the independent NFET observer.

    Conservative: the fused U is never below either signal, and when the
    observer is MORE uncertain than Claude's self-report (the overconfidence /
    blind-spot case) the gap is added back in — so a confident Claude over an
    answer the observer finds turbulent gets pushed toward GATHER/verify.
    """
    u_self = invert_p_correct(self_confidence)
    frames = list(nfet_frames or [])
    has_telemetry = bool(frames)
    u_nfet = aggregate_uncertainty(frames) if has_telemetry else None
    if u_nfet is None:
        u_fused = u_self
        disagreement = None
    else:
        gap = u_nfet - u_self                       # >0 => observer more alarmed
        u_fused = max(u_self, u_nfet) + 0.5 * max(0.0, gap)
        disagreement = round(abs(gap), 4)
    return {
        "self_confidence": round(float(self_confidence), 4),
        "u_self": round(u_self, 4),
        "u_nfet": round(u_nfet, 4) if u_nfet is not None else None,
        "u_fused": round(u_fused, 4),
        "disagreement": disagreement,
        "observer_more_alarmed": bool(u_nfet is not None and u_nfet > u_self + 0.5),
        "has_telemetry": has_telemetry,
        "n_frames": len(frames),
    }


# --- hash-chained receipt ledger -------------------------------------------

def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _last_receipt_sha() -> Optional[str]:
    try:
        last = None
        with LEDGER_PATH.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
        if last:
            return json.loads(last).get("receipt_sha")
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return None


def _append_ledger(entry: Dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --- the harness ------------------------------------------------------------

def claude_turn_receipt(task: str, answer: str, self_confidence: float,
                        action_kind: str = "answer",
                        nfet_frames: Optional[Sequence[Dict[str, Any]]] = None,
                        verified_outcome: Optional[bool] = None,
                        outcome_source: str = "",
                        ts: Optional[int] = None) -> Dict[str, Any]:
    """Wrap one Claude turn in the full LOLM loop and return a sealed receipt.

    ``self_confidence`` is Claude's own P(correct) in [0,1]. ``action_kind`` is
    the mechanical action the turn would take (answer / draft / edit / post /
    delete / payment / deploy / ...); it sets the risk tier and triggers the
    hard human gate. ``nfet_frames`` are the per-token telemetry traces of the
    independent observer (empty/None when no local model is loaded).

    ``verified_outcome`` is an EXTERNAL deterministic correctness signal for
    tasks the text-verifiers can't grade — e.g. a code change where the
    objective truth is "the test gate passed". It must be a real pass/fail
    result (with ``outcome_source`` naming it, e.g. "npm test"), never a
    feeling: the flywheel's no-vibes rule still holds. When given it takes
    precedence over the text-verifier signal for the flywheel + status.
    """
    answer = answer or ""
    profiles = risk_profile(task)
    verifiers = run_text_verifiers(answer)
    contract = check_contract(answer, parse_contract(task))
    assessment = critique_assess(task, answer, contract=contract,
                                 verifiers=verifiers, control_acted=False)

    # The objective correctness signal: an external verified outcome (e.g. a
    # passing test gate) when supplied, else the deterministic text-verifiers.
    objective = verified_outcome if verified_outcome is not None else verifiers.get("passed")

    fused = fuse_uncertainty(self_confidence, nfet_frames)
    gate = AutonomyGate(flywheel().calibrator())
    # We are never the gate's "blind spot" case: Claude's self-confidence is a
    # real uncertainty signal (u_self), and the flywheel calibrates it on real
    # outcomes. NFET telemetry is a *bonus* independent observer that can only
    # RAISE caution (never grant confidence) — its absence means "no second
    # opinion", not "no signal". has_telemetry is recorded for the reader.
    decision = gate.gate_action(
        fused["u_fused"], action_kind, risk_profiles=profiles,
        no_telemetry=False,
    )

    # If a verifier caught a wrong number, the gate's input was a lie — force a
    # verify/escalate regardless of how confident anyone was.
    if verifiers.get("passed") is False and decision.mode == "act":
        decision.mode = "gather"
        decision.reason = ("deterministic math_check FAILED — overriding ACT to "
                           "GATHER; a wrong number is not actionable")

    receipt = build_receipt(
        command=task, answer=answer, timeline=[],
        ended_by="claude_harness", profile="claude_turn",
        model_info={"model_requested": "claude-opus-4-8",
                    "model_used": "claude-opus-4-8", "fallback_used": False},
    )
    # Bolt the Claude-brain layers onto the standard receipt.
    receipt["reasoner"] = "claude"
    receipt["autonomy"] = decision.to_dict()
    receipt["second_opinion"] = fused
    receipt["assessment"] = {
        "verdict": assessment["verdict"],
        "labels": assessment["labels"],
        "risk_profile": assessment["risk_profile"],
        "math": assessment["math"],
        "contract": assessment["contract"],
        "plain": assessment["plain"],
    }
    receipt["hard_human_gated"] = (action_kind or "").lower() in HARD_HUMAN_GATE
    receipt["status_color"] = _status_color(verifiers, decision, objective)
    if verified_outcome is not None:
        receipt["external_outcome"] = {"verified": bool(verified_outcome),
                                       "source": outcome_source or "external"}

    # Hash-chain: link this receipt to the previous one in the ledger.
    stamp = int(ts if ts is not None else time.time())
    with _LEDGER_LOCK:
        prev = _last_receipt_sha()
        core = {
            "t": stamp, "prev": prev, "task_sha": _sha(task), "answer_sha": _sha(answer),
            "mode": decision.mode, "tier": decision.tier,
            "u_fused": fused["u_fused"], "math": assessment["math"],
            "status": receipt["status_color"],
        }
        receipt_sha = _sha(_canonical(core))
        ledger_entry = dict(core, receipt_sha=receipt_sha, action_kind=action_kind,
                            verdict=assessment["verdict"])
        _append_ledger(ledger_entry)

        # Flywheel: only record when there is an OBJECTIVE correctness signal
        # (a checkable number, or an external verified outcome like a test gate).
        # No objective signal -> no record (no vibes).
        recorded = False
        if objective is not None:
            recorded = flywheel().record(
                fused["u_fused"], bool(objective),
                meta={"sha": receipt_sha, "tier": decision.tier, "kind": action_kind,
                      "outcome_source": outcome_source or "text_verifiers"},
            )

    receipt["chain"] = {"prev_receipt_sha": prev, "receipt_sha": receipt_sha,
                        "flywheel_recorded": recorded}
    return receipt


def _status_color(verifiers: Dict[str, Any], decision: Any,
                  objective: Optional[bool] = None) -> str:
    if verifiers.get("passed") is False or objective is False:
        return "red"
    if decision.mode == "escalate":
        return "red"
    if decision.mode == "gather" or not decision.calibrated:
        return "yellow"
    return "green"


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def gate_only(action_kind: str, self_confidence: float = 0.85,
              task: str = "", nfet_frames: Optional[Sequence[Dict[str, Any]]] = None,
              ) -> Dict[str, Any]:
    """Lightweight pre-action gate (no receipt, no flywheel write).

    For the PreToolUse hook path: decide act/gather/escalate for an action
    BEFORE it runs, honouring the hard human gate. No torch needed when
    ``nfet_frames`` is None.
    """
    profiles = risk_profile(task) if task else []
    fused = fuse_uncertainty(self_confidence, nfet_frames)
    decision = AutonomyGate(flywheel().calibrator()).gate_action(
        fused["u_fused"], action_kind, risk_profiles=profiles,
        no_telemetry=False,
    )
    return {
        "action_kind": action_kind,
        "tier": classify_action_risk(action_kind, profiles),
        "decision": decision.to_dict(),
        "hard_human_gated": (action_kind or "").lower() in HARD_HUMAN_GATE,
        "second_opinion": fused,
    }


def ledger_tail(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        with LEDGER_PATH.open() as f:
            rows = [json.loads(x) for x in f if x.strip()]
        return rows[-limit:]
    except (FileNotFoundError, json.JSONDecodeError):
        return []
