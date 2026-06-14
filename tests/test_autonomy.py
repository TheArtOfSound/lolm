# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for uncertainty calibration + the autonomy gate (the math spine)."""

from lolm.calibration import (
    UncertaintyCalibrator,
    selective_threshold,
    aggregate_uncertainty,
    _pav,
)
from lolm.autonomy import (
    AutonomyGate,
    classify_action_risk,
    ACT,
    GATHER,
    ESCALATE,
    RISK_TIERS,
)


# ── isotonic calibration ──────────────────────────────────────────────────────

def test_pav_is_monotone():
    out = _pav([1, 0, 1, 0, 0, 1], [1] * 6, increasing=True)
    assert all(out[i] <= out[i + 1] + 1e-9 for i in range(len(out) - 1))


def test_calibrator_non_increasing_in_uncertainty():
    # Synthetic flywheel: low U mostly correct, high U mostly wrong.
    us, ys = [], []
    for u in [0.0, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0]:
        for _ in range(20):
            us.append(u)
        # true correctness probability falls with u
        p = max(0.0, 1.0 - u / 3.0)
        n_correct = round(20 * p)
        ys += [1] * n_correct + [0] * (20 - n_correct)
    cal = UncertaintyCalibrator().fit(us, ys)
    grid = [cal.p_correct(u) for u in [0.0, 0.5, 1.0, 2.0, 3.0]]
    assert all(grid[i] >= grid[i + 1] - 1e-9 for i in range(len(grid) - 1)), grid
    assert cal.p_correct(0.0) > 0.8 and cal.p_correct(3.0) < 0.2


def test_calibrator_clamps_outside_range_no_optimism():
    cal = UncertaintyCalibrator().fit([0.5, 1.0], [1, 0])
    # Far below lowest U => endpoint, never >1; far above => endpoint, never <0.
    assert 0.0 <= cal.p_correct(-5.0) <= 1.0
    assert cal.p_correct(100.0) == cal.p_correct(1.0)


# ── selective-risk guarantee ──────────────────────────────────────────────────

def test_selective_threshold_holds_target_risk():
    # Ordered by uncertainty: the accepted prefix must keep error <= target.
    us = [i / 100.0 for i in range(100)]          # 0.00 .. 0.99
    ys = [1 if i < 90 else 0 for i in range(100)]  # first 90 correct, last 10 wrong
    st = selective_threshold(us, ys, target_risk=0.05)
    assert st.feasible
    assert st.empirical_risk <= 0.05 + 1e-9
    # Should accept roughly the correct prefix, not everything.
    assert 0.5 < st.coverage <= 0.95


def test_selective_threshold_infeasible_when_even_best_is_wrong():
    us = [0.1, 0.2, 0.3]
    ys = [0, 0, 0]  # most-certain run is already wrong
    st = selective_threshold(us, ys, target_risk=0.01)
    assert st.feasible is False and st.coverage == 0.0


# ── the autonomy gate ─────────────────────────────────────────────────────────

def _confident_calibrator():
    # Low U -> high P(correct), high U -> low.
    us, ys = [], []
    for u in [0.0, 0.3, 0.8, 1.5, 2.5]:
        us += [u] * 40
        p = max(0.0, 1.0 - u / 3.2)
        k = round(40 * p)
        ys += [1] * k + [0] * (40 - k)
    return UncertaintyCalibrator().fit(us, ys)


def test_gate_acts_on_cheap_action_when_fairly_sure():
    gate = AutonomyGate(_confident_calibrator())
    d = gate.decide(uncertainty=0.3, tier="read")
    assert d.mode == ACT and d.margin >= 0


def test_gate_escalates_irreversible_unless_clearly_safe():
    gate = AutonomyGate(_confident_calibrator())
    # Same modest uncertainty that ACTs on a read must ESCALATE on money —
    # an irreversible action is never downgraded to gather.
    d = gate.decide(uncertainty=0.8, tier="irreversible")
    assert d.mode == ESCALATE, d.to_dict()


def test_gate_gathers_when_just_below_bar_and_recoverable():
    gate = AutonomyGate(_confident_calibrator())
    # Find an uncertainty that sits just under the external bar -> GATHER.
    d = gate.decide(uncertainty=1.2, tier="external")
    assert d.mode in (GATHER, ESCALATE)
    # And a clearly-too-high uncertainty escalates.
    assert gate.decide(uncertainty=2.5, tier="external").mode == ESCALATE


def test_no_telemetry_is_not_consent():
    gate = AutonomyGate(_confident_calibrator())
    # A blind spot forces escalation on any non-read tier, regardless of the
    # (meaningless) uncertainty value.
    assert gate.decide(0.0, "reversible", no_telemetry=True).mode == ESCALATE
    assert gate.decide(0.0, "read", no_telemetry=True).mode == ACT


def test_uncalibrated_prior_is_conservative():
    gate = AutonomyGate(calibrator=None)  # no flywheel yet
    d = gate.decide(uncertainty=0.0, tier="irreversible")
    assert d.calibrated is False
    # Even at zero measured uncertainty, the pessimistic prior should not let an
    # UNCALIBRATED agent autonomously fire an irreversible action.
    assert d.mode == ESCALATE


# ── risk classification composes with critique.risk_profile ───────────────────

def test_money_answer_lifts_reversible_button_to_irreversible():
    # A "draft" is mechanically reversible, but drafting on a wrong FINANCIAL
    # answer is treated as irreversible (you may act on the draft).
    assert classify_action_risk("draft", ["financial"]) == "irreversible"
    # Plain read stays read when no high-risk profile is present.
    assert classify_action_risk("read", ["factual"]) == "external"  # factual floor
    assert classify_action_risk("read", []) == "read"


def test_tiers_are_ordered_by_strictness():
    assert RISK_TIERS["read"] > RISK_TIERS["reversible"] > RISK_TIERS["external"] > RISK_TIERS["irreversible"]


def test_hard_human_gate_blocks_money_even_at_zero_uncertainty():
    gate = AutonomyGate(_confident_calibrator())
    # Calibrated P(correct) ~ 1.0 at U=0, yet a payment is hard-gated to a human.
    d = gate.gate_action(0.0, "payment", ["financial"])
    assert d.mode == ESCALATE and "hard-gated" in d.reason
    assert gate.gate_action(0.0, "delete").mode == ESCALATE
    # Opt-out is explicit and per-call.
    assert gate.gate_action(0.0, "payment", require_human=frozenset()).tier == "irreversible"


def test_aggregate_uncertainty_zero_without_telemetry():
    assert aggregate_uncertainty([]) == 0.0
    # A flat, low-entropy run reads as low uncertainty.
    frames = [{"graft_entropy": 1.0, "hidden_drift": 0.0} for _ in range(10)]
    assert aggregate_uncertainty(frames) >= 0.0
