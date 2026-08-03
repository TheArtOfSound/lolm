from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from local_ui.task_state_artifact_patch import install_patch
from lolm.control.task_state import (
    allow_finalize_from_state,
    load_or_init,
    observe_workspace_artifacts,
    policy_action,
    update_task_state,
)


def _criterion(state, criterion_id: str):
    return next(row for row in state.C if row.id == criterion_id)


def test_real_workspace_pdf_completes_artifact_criterion_without_stdout_trust(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path / "state"))
    state = load_or_init("create output.pdf", session="workspace-pdf")
    state = update_task_state(
        state,
        observation="PDF_READY output.pdf",
        action="run",
        result={
            "files": ["main.py"],
            "exit_ok": True,
            "produced_output": True,
        },
    )
    assert _criterion(state, "artifact").met is False
    assert allow_finalize_from_state(state) is False

    matching = observe_workspace_artifacts(state, ["main.py", "output.pdf"])
    assert matching == ["output.pdf"]
    assert _criterion(state, "artifact").met is True
    assert _criterion(state, "artifact").evidence == "output.pdf"
    assert allow_finalize_from_state(state) is True
    assert policy_action(state)["action"] == "finalize"


def test_stdout_claim_without_workspace_file_cannot_complete_artifact(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path / "state"))
    state = load_or_init("create output.pdf", session="stdout-only")
    state = update_task_state(
        state,
        observation="PDF_READY output.pdf and PDF contents verified",
        action="run",
        result={
            "files": ["main.py"],
            "exit_ok": True,
            "produced_output": True,
        },
    )
    assert observe_workspace_artifacts(state, ["main.py"]) == []
    assert _criterion(state, "artifact").met is False
    assert allow_finalize_from_state(state) is False


def test_code_agent_bridge_observes_generated_pdf_before_inner_policy_resumes(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path / "state"))
    state = load_or_init("create output.pdf", session="bridge-order")
    state = update_task_state(
        state,
        observation="green run with visible evidence",
        action="run",
        result={
            "files": ["main.py"],
            "exit_ok": True,
            "produced_output": True,
        },
    )
    assert policy_action(state)["action"] == "continue"

    class FakeAgent:
        def __init__(self):
            self.task_state = state
            self._files_written = ["main.py"]
            self.sb = SimpleNamespace(
                list_files=lambda limit=500: ["main.py", "output.pdf"],
            )
            self.policy_seen_after_command = None

        def run(self, task):
            yield {"event": "code_start", "data": {"task": task}}
            yield {
                "event": "command_finished",
                "data": {"command": "python3 main.py", "exit_code": 0},
            }
            # The wrapper must bind output.pdf before the original generator resumes.
            self.policy_seen_after_command = policy_action(self.task_state)
            yield {"event": "inner_policy", "data": self.policy_seen_after_command}

    install_patch(FakeAgent)
    agent = FakeAgent()
    events = list(agent.run("create output.pdf"))

    assert _criterion(agent.task_state, "artifact").met is True
    assert agent.policy_seen_after_command["action"] == "finalize"
    assert agent.policy_seen_after_command["block_finalize"] is False
    assert any(
        event.get("event") == "agent_note"
        and event.get("data", {}).get("evidence_source") == "sandbox_filesystem"
        for event in events
    )


def test_nonmatching_workspace_file_does_not_complete_pdf_task(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path / "state"))
    state = load_or_init("create output.pdf", session="wrong-medium")
    assert observe_workspace_artifacts(state, ["main.py", "output.txt"]) == []
    assert _criterion(state, "artifact").met is False
