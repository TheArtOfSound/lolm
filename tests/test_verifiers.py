# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the deterministic verifier layer."""

from lolm.verifiers import (
    verify_arithmetic,
    verify_percentages,
    run_text_verifiers,
    _tokenize,
    _evaluate,
)


def test_catches_the_3300_complaint():
    # The exact failure named in the audit: the model wrote $3,300 where the
    # figures it was given multiply to $1,650 (3 weeks x 10 hours x $55).
    text = "The extra cost is 3 x 10 x $55 = $3,300 over the pilot."
    checks = verify_arithmetic(text)
    assert len(checks) == 1
    c = checks[0]
    assert c["computed"] == 1650.0
    assert c["claimed"] == 3300.0
    assert c["ok"] is False


def test_correct_arithmetic_passes():
    text = "Total comes to 3 x 10 x $55 = $1,650."
    checks = verify_arithmetic(text)
    assert len(checks) == 1
    assert checks[0]["ok"] is True


def test_addition_and_precedence():
    # 100 + 2 x 50 = 200, left-to-right would wrongly give 5100.
    assert _evaluate(_tokenize("100 + 2 x 50")) == 200.0
    text = "Budget: 100 + 2 x 50 = 200 dollars."
    assert verify_arithmetic(text)[0]["ok"] is True
    bad = "Budget: 100 + 2 x 50 = 5100 dollars."
    assert verify_arithmetic(bad)[0]["ok"] is False


def test_word_operators():
    assert _evaluate(_tokenize("3 times 4")) == 12.0
    text = "That is 3 times 4 = 12 widgets."
    assert verify_arithmetic(text)[0]["ok"] is True


def test_commas_and_dollars_parsed():
    text = "1,200 + 450 = 1,650"
    c = verify_arithmetic(text)[0]
    assert c["computed"] == 1650.0 and c["ok"] is True


def test_percentage_check():
    good = verify_percentages("20% of 50 = 10")
    assert good and good[0]["ok"] is True
    bad = verify_percentages("20% of 50 is 15")
    assert bad and bad[0]["ok"] is False


def test_no_false_positive_on_date_range():
    # A year range must not be read as subtraction.
    assert verify_arithmetic("Active 2024-2026 across the program.") == []


def test_no_false_positive_on_variable_algebra():
    # x = y is not a numeric claim; nothing to check.
    assert verify_arithmetic("If x = y then the proof holds.") == []
    # A single number with no operator is not an equation.
    assert verify_arithmetic("The answer is 42.") == []


def test_division_by_zero_is_silent_not_crash():
    # Don't crash, don't emit a bogus failure.
    assert verify_arithmetic("10 / 0 = 0") == []


def test_prose_with_units_caught():
    # The exact form a real 70B wrote in a live run — units between operands.
    text = ("The team works 10 hours/week * 3 weeks = 30 hours. "
            "Then 30 hours * $55/hour = $1650. Total is $1650.")
    checks = verify_arithmetic(text)
    assert len(checks) == 2
    assert all(c["ok"] for c in checks)
    # "$55/hour" must NOT be read as division.
    assert any(c["computed"] == 1650.0 for c in checks)


def test_prose_with_units_catches_wrong_total():
    text = "Extra cost is 10 hours/week * 3 weeks * $55/hour = $3,300."
    checks = verify_arithmetic(text)
    assert checks and checks[0]["ok"] is False
    assert checks[0]["computed"] == 1650.0 and checks[0]["claimed"] == 3300.0


def test_no_double_count_on_bare_equation():
    # A bare equation must not be reported twice by bare + prose matchers.
    checks = verify_arithmetic("3 x 10 x $55 = $1,650")
    assert len(checks) == 1 and checks[0]["ok"] is True


def test_prose_no_false_positive():
    # No numeric result after '=' → nothing to check.
    assert verify_arithmetic("10 boxes x 3 shelves = plenty of space") == []
    # Unit rate alone, no equation.
    assert verify_arithmetic("We bill $55/hour for the work.") == []


def test_run_text_verifiers_summary():
    out = run_text_verifiers("Cost is 3 x 10 x $55 = $3,300.")
    assert out["checked"] == 1
    assert out["failed"] == 1
    assert out["passed"] is False
    assert out["labels"] == ["math_check_failed"]

    clean = run_text_verifiers("No numbers here, just prose about strategy.")
    assert clean["checked"] == 0
    assert clean["passed"] is None  # nothing checkable != success
    assert clean["labels"] == []

    ok = run_text_verifiers("3 x 10 x $55 = $1,650 and 20% of 50 = 10.")
    assert ok["checked"] == 2 and ok["failed"] == 0 and ok["passed"] is True
