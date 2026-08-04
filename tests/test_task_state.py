# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Persistent task-state control — agents that do not lose the plot.

Aligned with lolm.control.task_state (lolm.task_state.v1) as shipped on main.
"""

from lolm.control.task_state import (
    allow_finalize_from_state,
    load_or_init,
    policy_action,
    receipt_blob,
    save_task_state,
    update_task_state,
)


def init_task_state(task: str, **kwargs):
    """Compat helper used by evolution / oort tests."""
    return load_or_init(task, resume=False, **kwargs)


def test_init_extracts_completion_criteria():
    z = init_task_state(
        "Create solution.py defining wrap(text, width). Empty returns []. "
        "Raise ValueError for width < 1."
    )
    assert z.objective
    assert z.P
    assert z.C
    texts = " ".join(c.text for c in z.C).lower() + " " + (z.objective or "").lower()
    assert "solution" in texts or "wrap" in texts or "create" in texts


def test_update_and_policy_block_finalize_until_criteria_met(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path))
    z = init_task_state("Create solution.py defining is_valid(s). Empty is valid.")
    assert not allow_finalize_from_state(z)
    pol = policy_action(z)
    assert pol["block_finalize"] is True
    assert pol["action"] in ("continue", "verify", "retrieve", "branch")

    z = update_task_state(
        z,
        action="run",
        observation="ok",
        result={
            "files": ["solution.py"],
            "exit_ok": True,
            "green_runs": 2,
            "contract_ok": True,
            "produced_output": True,
        },
    )
    pol2 = policy_action(z)
    assert "action" in pol2
    save_task_state(z)
    z2 = load_or_init(z.objective, conversation_id=z.conversation_id, resume=True)
    # Same objective hash path when conversation empty — still persists by task_id file
    assert z2.step >= 0
    assert z2.objective


def test_blank_browser_forces_verify_or_branch():
    z = init_task_state("code a snake game on canvas")
    z = update_task_state(
        z,
        action="browser_verify",
        observation="the canvas is BLANK",
        result={
            "exit_ok": False,
            "browser_working": False,
            "renders": False,
            "stderr_tail": "the canvas is BLANK — only 1 colour",
            "thrash": 2,
            "files": ["index.html"],
        },
    )
    pol = policy_action(z)
    assert pol["block_finalize"] is True
    assert pol["action"] in ("verify", "branch", "continue", "retrieve")
    assert not allow_finalize_from_state(z)
    blob = receipt_blob(z)
    assert blob.get("task_id")
    assert "policy" in blob
    assert blob.get("finalize_allowed") is False


def test_premature_finalize_blocked_while_criteria_open():
    z = init_task_state("Create solution.py defining foo()")
    assert allow_finalize_from_state(z) is False
    pol = policy_action(z)
    assert pol["block_finalize"] is True


def test_multi_session_resume_survives_context_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path))
    conv = "conv-lti-test-1"
    z1 = load_or_init(
        "Build order state machine in solution.py",
        conversation_id=conv,
        resume=True,
    )
    z1 = update_task_state(
        z1,
        action="run",
        observation="illegal transition",
        result={
            "exit_ok": False,
            "stderr_tail": "illegal transition",
            "files": ["solution.py"],
            "thrash": 2,
        },
    )
    save_task_state(z1)
    tid = z1.task_id
    fails = len(z1.F)

    z2 = load_or_init(
        "Build order state machine in solution.py",
        conversation_id=conv,
        resume=True,
        context_reset=True,
    )
    assert z2.task_id == tid
    assert z2.context_resets >= 1
    assert len(z2.F) >= fails
    assert "order" in (z2.objective or "").lower()
