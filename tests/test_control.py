# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The 13 control tests from the NFET implementation spec (section 21)."""

import copy

from lolm.control import decide, build_control_receipt, receipt_hash, validate_receipt_claims
from lolm.control.signals import ControlSignals
from lolm.control.receipt import canonicalize
from lolm.control.memory_snapshot import snapshot_stats, live_vs_snapshot
from lolm.control.system_state import answer_system_state_question


# ── Tests 1-5: the controller chooses the right action from signals ──────────

def test_1_idle_decision():
    dp = decide({"goalPressure": 0.1, "uncertainty": 0.1, "toolNeed": 0.0,
                 "verificationNeed": 0.0, "safetyRisk": 0.0})
    assert dp.mode == "idle"
    assert dp.actionTriggered is False


def test_2_uncertainty_spike_triggers_verify():
    dp = decide({"uncertainty": 0.87, "verificationNeed": 0.8,
                 "contradictionRisk": 0.6, "safetyRisk": 0.0})
    assert dp.mode == "verify", dp.to_dict()
    assert dp.actionTriggered is True


def test_3_drift_spike_triggers_branch():
    dp = decide({"drift": 0.9, "uncertainty": 0.72, "branchNeed": 0.83,
                 "safetyRisk": 0.0})
    assert dp.mode == "branch", dp.to_dict()
    assert dp.actionTriggered is True


def test_4_goal_pressure_triggers_nudge():
    dp = decide({"goalPressure": 0.91, "userInterruptValue": 0.82, "safetyRisk": 0.05})
    assert dp.mode == "nudge", dp.to_dict()
    assert dp.actionTriggered is True


def test_5_high_safety_risk_refuses():
    dp = decide({"toolNeed": 0.9, "goalPressure": 0.9, "safetyRisk": 0.95})
    assert dp.mode == "refuse"
    assert dp.actionTriggered is False


# ── Tests 6-9, 12: receipt truth validator ───────────────────────────────────

def _receipt_with(action_count=0, spans=None, retrieval=False, branch=False,
                  baseline=False, nfet_ok=True):
    dp = decide({"uncertainty": 0.1, "safetyRisk": 0.0})
    actions = []
    if retrieval:
        actions.append({"type": "retrieve", "triggered": True, "executed": True})
    if branch:
        actions.append({"type": "branch", "triggered": True, "executed": True})
    r = build_control_receipt(
        dp, actions=actions or None,
        low_confidence_spans=[{"text": s} for s in (spans or [])],
        answer_quality={"status": "ungraded", "baselineCompared": baseline},
    )
    r["controllerClaim"]["actionCount"] = action_count
    r["controllerClaim"]["nfetControlled"] = True
    if not nfet_ok:
        r.pop("signals", None)
        r["decision"]["nfet"].pop("fieldEnergy", None)
    return r


def test_6_low_confidence_spans_without_action_requires_disclosure():
    r = _receipt_with(action_count=0, spans=["example span"])
    bad = validate_receipt_claims(r, "Here is the answer.")
    assert not bad["ok"]
    assert any("none crossed the action threshold" in m for m in bad["missing"])
    good = validate_receipt_claims(
        r, "Low-confidence spans were detected, but none crossed the action threshold.")
    assert good["ok"], good


def test_7_no_fake_retrieval_claim():
    r = _receipt_with(action_count=0, retrieval=False)
    res = validate_receipt_claims(r, "It checked notes and retrieved the answer.")
    assert not res["ok"]
    assert any(v["phrase"] in ("checked notes", "retrieved") for v in res["violations"])


def test_8_no_fake_branching_claim():
    r = _receipt_with(action_count=0, branch=False)
    res = validate_receipt_claims(r, "It tried two paths and branched.")
    assert not res["ok"]
    assert any(v["phrase"] == "tried two paths" for v in res["violations"])


def test_9_no_fake_baseline_claim():
    r = _receipt_with(action_count=1, baseline=False)
    res = validate_receipt_claims(r, "This answer beat a baseline chatbot.")
    assert not res["ok"]
    assert any(v["phrase"] == "beat a baseline" for v in res["violations"])


def test_12_nfet_claim_requires_nfet_fields():
    r = _receipt_with(action_count=1, nfet_ok=False)
    res = validate_receipt_claims(r, "NFET-controlled run.")
    assert not res["ok"]
    assert any("nfet field missing" in m for m in res["missing"])


# ── Test 10: run-start stats vs live stats, both labelled ────────────────────

def test_10_run_start_stats_differ_from_live():
    snap = snapshot_stats({"memories": 100, "recalls": 5, "conversations": 3,
                           "turns": 40}, scope="shared_demo")
    cmp = live_vs_snapshot(snap, {"memories": 103, "recalls": 6,
                                  "conversations": 3, "turns": 44})
    assert cmp["runStartLabel"] == "Run-start memory snapshot"
    assert cmp["liveLabel"] == "Current live memory stats"
    assert cmp["drifted"] is True
    assert "run-start snapshot" in cmp["note"]
    assert "not private user memory" in snap["scopeLabel"]


# ── Test 11: receipt hash changes when decision/action/signal fields change ──

def test_11_receipt_hash_changes_on_field_change():
    dp = decide({"uncertainty": 0.3, "verificationNeed": 0.2})
    r = build_control_receipt(dp)
    h0 = r["receiptHash"]
    assert h0 == receipt_hash(r)  # self-consistent
    mutated = copy.deepcopy(dict(r))
    mutated["decision"]["selectedAction"] = "verify"   # change a decision field
    assert receipt_hash(mutated) != h0
    mutated2 = copy.deepcopy(dict(r))
    mutated2["signals"]["drift"] = 0.99                # change a signal field
    assert receipt_hash(mutated2) != h0


# ── Test 13: deterministic system-state answer (not speculation) ─────────────

def test_13_deterministic_system_state_answer():
    snap = snapshot_stats({"memories": 100, "turns": 40}, scope="shared_demo")
    ans = answer_system_state_question(
        "Why do memory stats differ from /brain/stats?",
        current_stats={"memories": 103, "turns": 44},
        receipt_snapshot=snap)
    assert ans is not None and ans["source"] == "metadata"
    text = ans["answer"].lower()
    assert "live" in text and "run-start snapshot" in text
    # Must NOT speculate.
    assert "may be a layer" not in text and "outside" not in text


# ── Bonus: prompt-time never idles (answers instead) ─────────────────────────

def test_prompt_time_answers_when_no_action_needed():
    dp = decide({"uncertainty": 0.1}, input_type="user_prompt")
    assert dp.mode == "answer" and dp.actionTriggered is False
