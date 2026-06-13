# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Termination taxonomy (#6): budget/stall/timeout never read as a clean finish."""

from lolm.run_receipt import build_receipt

CLEAN_TASK = ("Explain in one sentence why the sky is blue.",
              "The sky is blue because air scatters short blue wavelengths more than long ones.")


def _receipt(ended_by, cmd=CLEAN_TASK[0], ans=CLEAN_TASK[1], timeline=None):
    return build_receipt(cmd, ans, timeline or [], ended_by)


def test_controller_finish_is_clean():
    t = _receipt("nfet_finalize")["termination"]
    assert t["category"] == "controller_finish" and t["clean_finish"] is True and t["demote"] is False


def test_budget_limit_is_demoted():
    t = _receipt("segment_budget")["termination"]
    assert t["category"] == "budget_limit" and t["clean_finish"] is False and t["demote"] is True


def test_stall_and_timeout_demoted():
    assert _receipt("repetition_stall")["termination"]["category"] == "stalled"
    assert _receipt("timeout")["termination"]["demote"] is True
    assert _receipt("user_stop")["termination"]["category"] == "user_stop"


def test_green_requires_clean_finish():
    # A contract-passing answer that ended on budget must NOT be green.
    cmd = "## Result\nGive the result."
    ans = "## Result\nDone."
    budget = build_receipt(cmd, ans, [], "segment_budget")
    finish = build_receipt(cmd, ans, [], "nfet_finalize")
    assert budget["status_color"] != "green"
    assert finish["status_color"] == "green"
