# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for duration verifiers and word-count contracts (#4 extension)."""

from lolm.verifiers import verify_durations, run_text_verifiers
from lolm.run_receipt import parse_contract, check_contract


def test_duration_conversion_correct():
    c = verify_durations("That is 3 weeks = 21 days of work.")
    assert len(c) == 1 and c[0]["ok"] is True


def test_duration_conversion_wrong():
    c = verify_durations("The deadline is 3 weeks = 20 days away.")
    assert c and c[0]["ok"] is False


def test_duration_hours_minutes():
    assert verify_durations("2 hours is 120 minutes")[0]["ok"] is True
    assert verify_durations("2 hours is 100 minutes")[0]["ok"] is False


def test_duration_ignores_ambiguous_months():
    # months/years are ambiguous → never strict-checked
    assert verify_durations("3 months = 90 days") == []


def test_durations_flow_into_run_text_verifiers():
    out = run_text_verifiers("Timeline: 3 weeks = 20 days.")
    assert out["failed"] == 1 and out["labels"] == ["math_check_failed"]


def test_word_count_contract_parsed():
    assert parse_contract("Write a 700-word scene.")["word_limit"] == {"kind": "target", "count": 700}
    assert parse_contract("Give exactly 500 words.")["word_limit"] == {"kind": "exact", "count": 500}
    assert parse_contract("At least 300 words please.")["word_limit"] == {"kind": "min", "count": 300}
    assert parse_contract("Keep it under 150 words.")["word_limit"] == {"kind": "max", "count": 150}


def test_word_count_max_violation_flagged():
    contract = parse_contract("Summarize in under 50 words.")
    long_answer = " ".join(["word"] * 200)
    res = check_contract(long_answer, contract)
    assert "length_requirement_failed" in res["reasons"]


def test_word_count_within_tolerance_passes():
    contract = parse_contract("Write about 100 words.")
    ok_answer = " ".join(["word"] * 95)
    res = check_contract(ok_answer, contract)
    assert "length_requirement_failed" not in res["reasons"]


def test_word_count_min_violation_flagged():
    contract = parse_contract("Write at least 500 words.")
    short = " ".join(["word"] * 50)
    assert "length_requirement_failed" in check_contract(short, contract)["reasons"]
