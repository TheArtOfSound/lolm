# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Rotating receipt signatures + retrieval usefulness metrics."""
import os

import pytest

os.environ["LOLM_RECEIPT_SIGNING_KEYS"] = "qira-test-2026:0123456789abcdef0123456789abcdef"
os.environ["LOLM_RECEIPT_ACTIVE_KID"] = "qira-test-2026"


def test_sign_and_verify_roundtrip():
    from local_ui.receipt_sign import sign_code_receipt, verify_code_receipt
    core = {
        "schema": "lolm.code.receipt.v2", "run_id": "run_test",
        "kind": "code_agent", "task": "print 42", "summary": "ok", "ts": 1,
        "steps": 1, "ran": True, "produced_output": True, "stuck": False,
        "budget_hit": False, "error": "", "files": ["h.py"], "green_runs": 1,
        "failed_runs": 0, "verifies": 0, "expected": ["42"], "expected_ok": True,
        "missing_expected": [], "last_stdout_tail": "42", "trail": [],
        "syntax_ok": True, "syntax_error": "", "syntax_checked": ["h.py"],
        "ok": True, "visual_missing_html": False, "verdict": "shipped",
        "verification": {"syntax_ok": True, "execution_ok": True,
                         "contract_ok": True, "artifact_manifest_ok": True,
                         "artifact_manifest_sha256": "a" * 64},
    }
    sealed = sign_code_receipt(core)
    v = verify_code_receipt(sealed)
    assert v["receipt_hash_match"] is True
    assert v["signature_valid"] is True
    assert v["integrity"]["verified"] is True
    assert v["signing_key"] == "qira-test-2026"


def test_tamper_breaks_signature():
    from local_ui.receipt_sign import sign_code_receipt, verify_code_receipt
    sealed = sign_code_receipt({
        "schema": "lolm.code.receipt.v2", "run_id": "run_test",
        "kind": "code_agent", "task": "x", "ok": True, "files": [], "trail": [],
        "syntax_ok": True, "ran": True, "produced_output": True, "stuck": False,
        "budget_hit": False, "error": "", "green_runs": 1, "failed_runs": 0,
        "verifies": 0, "expected": [], "expected_ok": True, "missing_expected": [],
        "last_stdout_tail": "", "summary": "", "ts": 1, "steps": 1,
        "syntax_error": "", "syntax_checked": [], "visual_missing_html": False,
        "verdict": "shipped", "verification": {"syntax_ok": True,
            "execution_ok": True, "contract_ok": True,
            "artifact_manifest_ok": True,
            "artifact_manifest_sha256": "b" * 64},
    })
    sealed["task"] = "TAMPERED"
    v = verify_code_receipt(sealed)
    assert v["receipt_hash_match"] is False or v["signature_valid"] is False
    assert v["integrity"]["verified"] is False


def test_incomplete_artifact_manifest_cannot_verify_as_shippable():
    from local_ui.receipt_sign import sign_code_receipt, verify_code_receipt
    core = {
        "schema": "lolm.code.receipt.v2", "run_id": "run_incomplete",
        "kind": "code_agent", "task": "binary output", "ok": True,
        "syntax_ok": True, "verdict": "shipped",
        "verification": {"syntax_ok": True, "execution_ok": True,
                         "contract_ok": True, "artifact_manifest_ok": False,
                         "artifact_manifest_sha256": "c" * 64},
    }
    sealed = sign_code_receipt(core)
    assert verify_code_receipt(sealed)["integrity"]["verified"] is False


def test_usefulness_marks_answer_use():
    from lolm.retrieval_report import usefulness_metrics
    ev = [
        {"kind": "web", "text": "Specific impulse of chemical rockets is ~450 s",
         "url": "https://example.com/isp"},
        {"kind": "memory", "text": "cookie sign in skip to content"},
    ]
    u = usefulness_metrics(
        ev,
        answer="The rocket's specific impulse was about 450 s.",
        command="explain chemical rocket performance",
    )
    assert u["used_in_answer"] >= 1
    assert u["success"] is True
    assert u["verdict"] in ("useful", "partial")
    assert u["decorative"] >= 1


def test_usefulness_empty_is_not_success_claim():
    from lolm.retrieval_report import usefulness_metrics
    u = usefulness_metrics([], answer="hello", command="hi")
    assert u["retrieved"] == 0
    assert u["verdict"] == "empty"
