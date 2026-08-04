# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Persistent task-state control — agents that do not lose the plot."""

import json
from pathlib import Path

from lolm.control.task_state import (
    allow_finalize_from_state,
    init_task_state,
    load_or_init,
    policy_action,
    receipt_blob,
    save_task_state,
    update_task_state,
)


def test_init_extracts_completion_criteria():
    z = init_task_state(
        "Create solution.py defining wrap(text, width). Empty returns []. "
        "Raise ValueError for width < 1."
    )
    assert z.objective
    assert z.G and z.G[0].status == "active"
    assert z.P
    texts = " ".join(c.text for c in z.C).lower()
    assert "solution.py" in texts or "example" in texts or "reject" in texts


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
    # Criteria may still be partially open depending on extractors
    pol2 = policy_action(z)
    assert "action" in pol2
    save_task_state(z)
    z2 = load_or_init(z.objective, task_id=z.task_id)
    assert z2.task_id == z.task_id
    assert z2.step >= 1


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
    assert blob.get("task_state") is True
    assert "integrity" in blob


def test_premature_finalize_counter():
    z = init_task_state("Create solution.py defining foo()")
    n0 = z.premature_finalize_blocked
    assert allow_finalize_from_state(z) is False
    assert z.premature_finalize_blocked > n0


def test_multi_session_resume_survives_context_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path))
    from lolm.control.task_state import load_or_init, mark_context_reset, save_task_state

    conv = "conv-lti-test-1"
    z1 = load_or_init(
        "Build order state machine in solution.py",
        conversation_id=conv,
        resume=True,
    )
    z1 = update_task_state(
        z1, action="run", result={"exit_ok": False, "stderr_tail": "illegal transition",
                                    "files": ["solution.py"], "thrash": 2},
    )
    save_task_state(z1)
    tid = z1.task_id
    fails = len(z1.F)

    # Simulate days later: context wipe but same conversation_id
    z2 = load_or_init(
        "Build order state machine in solution.py — also handle refunds",
        conversation_id=conv,
        resume=True,
        context_reset=True,
    )
    assert z2.task_id == tid
    assert z2.context_resets >= 1
    assert len(z2.F) >= fails  # failures not forgotten
    assert any("refund" in g.text.lower() or "order" in g.text.lower() for g in z2.G)
    # Integrity: same plot after wipe (objective + dead-end memory)
    assert "order" in (z2.objective or "").lower()
    assert z2.interruptions >= 1


def test_lti_harness_continuous_beats_plain(tmp_path, monkeypatch):
    """Formal LTI: continuous z_t under resets should not lose the plot."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    out = tmp_path / "out"
    out.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent
                             / "scripts" / "lti_harness.py"),
         "--steps", "120", "--resets", "6", "--seed", "7",
         "--out", str(out)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    files = list(out.glob("lti-harness-*.json"))
    assert files
    data = json.loads(files[0].read_text())
    assert data["winner"] in ("continuous", "tie")
    assert data["delta_LTI"] >= 0
    assert data["arms"]["continuous"]["false_finalize"] <= data["arms"]["plain"]["false_finalize"]
