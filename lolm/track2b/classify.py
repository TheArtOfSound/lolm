# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Admission vs agent-failure classification for Track 2B runs."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class RunClass(str, Enum):
    ADMISSIBLE_PASS = "admissible_pass"          # admitted + oracle pass
    ADMITTED = "admitted"                        # evidence OK; oracle not yet applied
    AGENT_FAILURE = "agent_failure"              # admitted + competence fail
    INADMISSIBLE = "inadmissible"                # harness/server evidence fail
    NOT_ADMITTED = "not_admitted"                # HTTP/auth/rate-limit before start
    TIMEOUT = "timeout"                          # admitted then idle/hard timeout


def classify_run(
    *,
    http_status: Optional[int] = None,
    admitted: bool = False,
    code_start: bool = False,
    code_done: bool = False,
    code_receipt: bool = False,
    final_workspace: bool = False,
    server_sha_ok: bool = False,
    hash_agreement: bool = False,
    fixture_bound: bool = False,
    stream_complete: bool = False,
    secret_leak: bool = False,
    oracle_ok: Optional[bool] = None,
    timed_out: bool = False,
    pre_admission_error: str = "",
) -> tuple[RunClass, List[str]]:
    reasons: List[str] = []

    if secret_leak:
        return RunClass.INADMISSIBLE, ["api_key_in_artifact"]

    if http_status in (401, 403, 429, 503) or (http_status and http_status >= 400 and not admitted):
        reasons.append(pre_admission_error or f"http_{http_status}")
        return RunClass.NOT_ADMITTED, reasons

    if pre_admission_error and not admitted:
        return RunClass.NOT_ADMITTED, [pre_admission_error]

    if not admitted or not code_start:
        if timed_out and admitted:
            return RunClass.TIMEOUT, ["timeout_before_code_start"]
        return RunClass.NOT_ADMITTED, reasons or ["no_code_start"]

    # Idle/hard timeout after admission is a first-class outcome (not agent failure).
    if timed_out and not (code_done and code_receipt and final_workspace):
        return RunClass.TIMEOUT, ["idle_or_hard_timeout_after_admission"]

    if not server_sha_ok:
        reasons.append("server_sha_missing_or_mismatch")
    if not code_done:
        reasons.append("code_done_absent")
    if not code_receipt:
        reasons.append("code_receipt_absent")
    if not final_workspace:
        reasons.append("final_workspace_absent")
    if not hash_agreement:
        reasons.append("tree_hash_disagreement")
    if not fixture_bound:
        reasons.append("fixture_package_unbound")
    if not stream_complete:
        reasons.append("stream_incomplete")

    if reasons:
        return RunClass.INADMISSIBLE, reasons

    if oracle_ok is True:
        return RunClass.ADMISSIBLE_PASS, []
    if oracle_ok is False:
        return RunClass.AGENT_FAILURE, ["oracle_failed"]
    return RunClass.ADMITTED, []
