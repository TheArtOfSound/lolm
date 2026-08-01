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


def test_signed_receipt_is_a_frozen_snapshot_of_nested_runtime_state():
    """A later controller-state mutation must not corrupt an emitted receipt."""
    from local_ui.receipt_sign import sign_code_receipt, verify_code_receipt

    timeline = [{"label": "continue", "scores": [0.25]}]
    core = {
        "schema": "lolm.code.receipt.v2", "run_id": "run_nested",
        "kind": "code_agent", "task": "x", "ok": True,
        "syntax_ok": True, "verdict": "shipped", "nfet": {"timeline": timeline},
        "verification": {
            "syntax_ok": True, "execution_ok": True, "contract_ok": True,
            "artifact_manifest_ok": True,
            "artifact_manifest_sha256": "e" * 64,
        },
    }
    sealed = sign_code_receipt(core)

    timeline[0]["scores"].append(0.75)
    timeline.append({"label": "finalize"})

    assert sealed["nfet"]["timeline"] == [{"label": "continue", "scores": [0.25]}]
    assert verify_code_receipt(sealed)["integrity"]["verified"] is True


def test_signed_receipt_normalizes_integral_floats_for_javascript_roundtrip():
    """JSON.parse/stringify turns 0.0 and 2.0 into 0 and 2; the seal must agree."""
    from local_ui.receipt_sign import sign_code_receipt, verify_code_receipt

    sealed = sign_code_receipt({
        "schema": "lolm.code.receipt.v2", "run_id": "run_numbers",
        "ok": True, "syntax_ok": True, "verdict": "shipped",
        "nfet": {"zscores": {"gate": 0.0}},
        "task_state": {"integrity": {"denominator": 2.0}},
        "verification": {
            "syntax_ok": True, "execution_ok": True, "contract_ok": True,
            "artifact_manifest_ok": True,
            "artifact_manifest_sha256": "f" * 64,
        },
    })

    assert type(sealed["nfet"]["zscores"]["gate"]) is int
    assert type(sealed["task_state"]["integrity"]["denominator"]) is int
    assert verify_code_receipt(sealed)["integrity"]["verified"] is True


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


def test_receipt_signing_timestamp_is_authenticated_and_future_time_fails_closed():
    import time
    from local_ui.receipt_sign import sign_code_receipt, verify_code_receipt

    sealed = sign_code_receipt({
        "schema": "lolm.code.receipt.v2", "run_id": "run_time",
        "verdict": "shipped", "ok": True, "syntax_ok": True,
        "verification": {
            "syntax_ok": True, "execution_ok": True, "contract_ok": True,
            "artifact_manifest_ok": True,
            "artifact_manifest_sha256": "d" * 64,
        },
    })
    assert verify_code_receipt(sealed)["integrity"]["verified"] is True

    tampered = dict(sealed)
    tampered["signed_at"] = int(time.time()) + 86_400
    result = verify_code_receipt(tampered)
    assert result["timestamp_valid"] is False
    assert result["integrity"]["verified"] is False
