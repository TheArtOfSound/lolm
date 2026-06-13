# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the deterministic post-run critique (complaints #2 and #3)."""

from lolm.critique import risk_profile, should_audit, assess


# ── #2: prompt risk classification drives controller aggression ───────────────

def test_financial_prompt_triggers_audit():
    cmd = "The pilot is 3 weeks at 10 extra hours/week at $55/hour. What is the extra cost?"
    tags = set(risk_profile(cmd))
    assert "financial" in tags
    assert should_audit(cmd) is True


def test_logic_prompt_triggers_audit():
    assert should_audit("Solve this formal logic puzzle. Return SATISFIABLE or UNSATISFIABLE.")


def test_underdetermined_prompt_triggers_audit():
    assert should_audit("Determine who opened the vault. Do not guess.")


def test_smalltalk_does_not_trigger_audit():
    assert should_audit("hey, how's it going?") is False
    assert risk_profile("Tell me a fun fact about otters.") == []


# ── #3: answer grading ────────────────────────────────────────────────────────

def test_overclaim_on_underdetermined_is_caught():
    # The exact T4 failure: prompt says don't guess; answer names a culprit.
    cmd = ("Four people had vault access. Determine who opened it. Do not guess. "
           "Identify what follows and what additional evidence is needed.")
    bad = "The answer is Morgan. Morgan entered the vault based on the motion sensor."
    out = assess(cmd, bad)
    assert out["overclaim"] is True
    assert "overclaim_on_underdetermined" in out["labels"]
    assert out["verdict"] == "answer_overclaimed"


def test_proper_hedge_on_underdetermined_passes():
    cmd = "Determine who opened the vault. Do not guess."
    good = ("Underdetermined. The motion sensor does not imply Morgan entered, and the "
            "missing badge log is insufficient. More information is needed.")
    out = assess(cmd, good)
    assert out["overclaim"] is False
    assert "overclaim_on_underdetermined" not in out["labels"]


def test_math_failure_flows_into_critique():
    out = assess("What is the extra cost?", "It is $3,300.",
                 verifiers={"passed": False})
    assert "math_check_failed" in out["labels"]
    assert out["verdict"] == "answer_math_failed"


def test_high_stakes_unverified_flag():
    # Financial prompt, no control action, no math confirmed -> flagged.
    out = assess("What's the total budget in dollars?", "Roughly forty thousand.",
                 control_acted=False, verifiers={"passed": None})
    assert out["audit_expected"] is True
    assert "high_stakes_unverified" in out["labels"]
    # Same prompt, but a verify pass fired -> satisfied.
    ok = assess("What's the total budget in dollars?", "It is $40,000.",
                control_acted=True, verifiers={"passed": None})
    assert "high_stakes_unverified" not in ok["labels"]


def test_contract_failure_flows_through():
    out = assess("Write exactly three hypotheses.", "Only one hypothesis here.",
                 contract={"passed": False})
    assert "task_contract_failed" in out["labels"]


def test_clean_answer_makes_no_false_claim_of_quality():
    out = assess("Explain photosynthesis briefly.", "Plants convert light to energy.")
    # No deterministic fault, but the verdict must NOT assert the answer is good.
    assert out["labels"] == []
    assert out["verdict"] == "answer_no_deterministic_fault"
    assert "not proof" in out["plain"]
