from __future__ import annotations

from pathlib import Path

from lolm.control.task_state import (
    allow_finalize_from_state,
    load_or_init,
    policy_action,
    save_task_state,
    update_task_state,
)


def test_task_state_persists_and_allows_finalize(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path))
    state = load_or_init(
        "create a PDF report",
        session="s1",
        conversation_id="c1",
        owner="owner",
    )
    assert state.task_id
    assert not allow_finalize_from_state(state)
    state = update_task_state(
        state,
        observation="PDF generated at output.pdf",
        action="run",
        result={"files": ["main.py", "output.pdf"], "exit_ok": True, "produced_output": True},
    )
    assert allow_finalize_from_state(state)
    assert policy_action(state)["action"] == "finalize"
    save_task_state(state)

    resumed = load_or_init(
        "create a PDF report",
        session="s1",
        conversation_id="c1",
        owner="owner",
        resume=True,
    )
    assert resumed.task_id == state.task_id
    assert resumed.step == 1
    assert allow_finalize_from_state(resumed)


def test_task_state_repeated_failure_forces_branch(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path))
    state = load_or_init("fix parser", session="s2")
    for _ in range(2):
        state = update_task_state(
            state,
            observation="same syntax error",
            action="run_fail",
            result={"files": ["parser.py"], "exit_ok": False, "produced_output": False},
        )
    decision = policy_action(state)
    assert decision["action"] == "branch"
    assert decision["force_branch"] is True
    assert decision["block_finalize"] is True
