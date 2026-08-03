# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Bind program-generated workspace files into persistent task state.

CodeAgent emits ``command_finished`` before its internal task-state update. This
wrapper observes the real sandbox tree at that boundary, so artifacts created by a
program, rather than a FILE/EDIT action, are available to the completion policy before
it decides whether finalization is allowed. It never trusts stdout or model claims.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List


def _workspace_paths(agent: Any) -> List[str]:
    paths: List[str] = []
    for raw in list(getattr(agent, "_files_written", []) or []):
        path = str(raw or "").strip().replace("\\", "/")
        if path and path not in paths:
            paths.append(path)
    try:
        discovered = list(agent.sb.list_files(limit=500))
    except Exception:
        discovered = []
    for raw in discovered:
        path = str(raw or "").strip().replace("\\", "/")
        if path and path not in paths:
            paths.append(path)
    return paths


def install_patch(code_agent_class: Any) -> None:
    if getattr(code_agent_class, "_task_state_artifact_patch", False):
        return

    original_run = code_agent_class.run

    def _run(self: Any, task: str) -> Iterator[Dict[str, Any]]:
        for event in original_run(self, task):
            note = None
            if event.get("event") == "command_finished" and getattr(self, "task_state", None) is not None:
                try:
                    from lolm.control.task_state import (
                        observe_workspace_artifacts,
                        save_task_state,
                    )

                    before = next(
                        (row.met for row in self.task_state.C if row.id == "artifact"),
                        False,
                    )
                    matching = observe_workspace_artifacts(
                        self.task_state,
                        _workspace_paths(self),
                    )
                    after = next(
                        (row.met for row in self.task_state.C if row.id == "artifact"),
                        False,
                    )
                    if matching:
                        save_task_state(self.task_state)
                    if matching and after and not before:
                        note = {
                            "event": "agent_note",
                            "data": {
                                "text": (
                                    "task state observed generated artifact from sandbox: "
                                    + ", ".join(matching[-4:])
                                ),
                                "task_state_artifacts": matching[-12:],
                                "evidence_source": "sandbox_filesystem",
                            },
                        }
                except Exception:
                    # Preserve the original fail-closed CodeAgent behavior. A missing
                    # observation cannot authorize completion.
                    pass
            yield event
            if note is not None:
                yield note

    code_agent_class.run = _run
    code_agent_class._task_state_artifact_patch = True
