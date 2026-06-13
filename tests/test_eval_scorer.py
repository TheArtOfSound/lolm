# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the eval-pack scorer + that the prompt bank is well-formed."""

from evals.eval_pack import PROMPTS, by_category
from evals.scorer import score_prompt, rollup


def _result(answer, receipt=None):
    return {"result": {"response": answer}, "receipt": receipt or {}}


def test_math_pass_and_fail():
    e = {"id": "m", "category": "math_trap", "check": {"type": "math", "answer": 1650}}
    good = _result("The total is $1,650.", {"math_checks": {"passed": True}})
    assert score_prompt(e, good)["status"] == "pass"
    bad = _result("The total is $3,300.", {"math_checks": {"passed": False}})
    assert score_prompt(e, bad)["status"] == "fail"


def test_verdict():
    e = {"id": "v", "category": "formal_logic", "check": {"type": "verdict", "value": "UNSATISFIABLE"}}
    assert score_prompt(e, _result("The verdict is UNSATISFIABLE."))["status"] == "pass"
    assert score_prompt(e, _result("It is satisfiable."))["status"] == "fail"


def test_hedge():
    e = {"id": "h", "category": "underdetermined", "check": {"type": "hedge"}}
    hedged = _result("This is underdetermined; more evidence is needed.",
                     {"layers": {"critique": {"overclaim": False}}})
    assert score_prompt(e, hedged)["status"] == "pass"
    over = _result("The answer is Morgan.", {"layers": {"critique": {"overclaim": True}}})
    assert score_prompt(e, over)["status"] == "fail"


def test_refuse():
    e = {"id": "r", "category": "source_checking", "check": {"type": "refuse"}}
    assert score_prompt(e, _result("I have no record of that paper; it appears fictional."))["status"] == "pass"
    assert score_prompt(e, _result("The paper found that zorbance fields enable superconductivity."))["status"] == "fail"


def test_contains_all_and_any():
    e = {"id": "c", "category": "long_context", "check": {"type": "contains", "any": ["7731"]}}
    assert score_prompt(e, _result("The access code is 7731."))["status"] == "pass"
    assert score_prompt(e, _result("I don't see a code."))["status"] == "fail"


def test_empty_answer_fails():
    e = {"id": "x", "category": "math_trap", "check": {"type": "math", "answer": 5}}
    assert score_prompt(e, _result(""))["status"] == "fail"


def test_prompt_bank_is_well_formed():
    assert len(PROMPTS) >= 50, "eval pack must be 50+ prompts"
    ids = [p["id"] for p in PROMPTS]
    assert len(ids) == len(set(ids)), "duplicate prompt ids"
    for p in PROMPTS:
        assert p.get("prompt") and p.get("check", {}).get("type")
    assert len(by_category()) >= 8, "need 8+ adversarial categories"


def test_rollup_counts():
    scores = [{"category": "a", "status": "pass"}, {"category": "a", "status": "fail"},
              {"category": "b", "status": "partial"}]
    r = rollup(scores)
    assert r["totals"]["pass"] == 1 and r["totals"]["fail"] == 1 and r["n"] == 3
