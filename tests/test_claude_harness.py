# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The Claude-brain LOLM harness: Claude reasons, LOLM's loop disciplines it."""

from __future__ import annotations

import importlib

import pytest

from lolm.calibration import _default_p_correct


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    """Fresh module with ledger/flywheel redirected to a temp dir per test."""
    import local_ui.claude_harness as ch
    importlib.reload(ch)
    monkeypatch.setattr(ch, "LEDGER_PATH", tmp_path / "receipts.jsonl")
    monkeypatch.setattr(ch, "FLYWHEEL_PATH", tmp_path / "flywheel.jsonl")
    monkeypatch.setattr(ch, "_FLYWHEEL", None)
    return ch


def test_self_confidence_roundtrips_through_the_gate_prior(harness):
    # u_self is the exact inverse of the gate's logistic prior, so a verbalized
    # P(correct) re-maps back to itself in the same domain NFET uses.
    for p in (0.6, 0.8, 0.9, 0.97):
        u = harness.invert_p_correct(p)
        assert abs(_default_p_correct(u) - p) < 1e-6


def test_independent_observer_only_raises_caution(harness):
    base = harness.fuse_uncertainty(0.9, None)["u_fused"]
    calm = harness.fuse_uncertainty(0.9, [{"graft_entropy": 0.0}] * 8)["u_fused"]
    alarmed = harness.fuse_uncertainty(
        0.9, [{"graft_entropy": 5.0, "hidden_drift": 1.0}] * 8)["u_fused"]
    # A calm observer never grants extra confidence (never below self alone);
    # an alarmed observer pushes uncertainty up.
    assert calm >= base - 1e-9
    assert alarmed > base


def test_wrong_math_is_red_and_overrides_act(harness):
    r = harness.claude_turn_receipt(
        "Budget?", "Your total is 1000 + 1000 = 3000 per month.", 0.95)
    assert r["status_color"] == "red"
    assert "math_check_failed" in r["assessment"]["labels"]
    assert r["autonomy"]["mode"] in ("gather", "escalate")  # never 'act'


def test_hard_human_gate_escalates_regardless_of_confidence(harness):
    for kind in ("payment", "send", "delete", "deploy"):
        g = harness.gate_only(kind, self_confidence=0.999)
        assert g["hard_human_gated"] is True
        assert g["decision"]["mode"] == "escalate"


def test_confident_reversible_edit_acts(harness):
    r = harness.claude_turn_receipt("rename a var", "done", 0.99, action_kind="edit")
    assert r["autonomy"]["mode"] == "act"
    assert r["autonomy"]["tier"] == "reversible"


def test_receipts_form_a_hash_chain(harness):
    harness.claude_turn_receipt("q1", "a1", 0.9)
    harness.claude_turn_receipt("q2", "a2", 0.9)
    rows = harness.ledger_tail(10)
    assert len(rows) == 2
    assert rows[0]["prev"] is None                      # genesis
    assert rows[1]["prev"] == rows[0]["receipt_sha"]    # chained


def test_flywheel_records_only_objective_outcomes(harness):
    # An answer with a checkable number -> recorded; pure prose -> not (no vibes).
    with_number = harness.claude_turn_receipt("q", "2 + 2 = 4", 0.9)
    prose = harness.claude_turn_receipt("opinion?", "I think blue is nice.", 0.9)
    assert with_number["chain"]["flywheel_recorded"] is True
    assert prose["chain"]["flywheel_recorded"] is False
    assert harness.flywheel().stats()["n"] == 1
