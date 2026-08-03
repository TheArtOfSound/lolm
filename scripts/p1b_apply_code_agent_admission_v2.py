#!/usr/bin/env python3
"""Apply P1-B structured CodeAgent admission against the current controller layout."""
from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def patch_sandbox_binding() -> None:
    path = Path("local_ui/sandbox.py")
    text = path.read_text()
    if "expected_admission_fingerprint" in text:
        print("sandbox fingerprint binding already patched")
        return
    text = replace_once(
        text,
        '    def run(self, command: str, timeout: int = 120,\n'
        '            isolated: Optional[bool] = None, *,\n'
        '            admission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:',
        '    def run(self, command: str, timeout: int = 120,\n'
        '            isolated: Optional[bool] = None, *,\n'
        '            admission_context: Optional[Dict[str, Any]] = None,\n'
        '            expected_admission_fingerprint: str = "") -> Dict[str, Any]:',
        "sandbox expected fingerprint signature",
    )
    anchor = '''        if not decision.accepted:
            codes = ",".join(decision.reason_codes) or "rejected"
'''
    insertion = '''        if expected_admission_fingerprint and decision.fingerprint != expected_admission_fingerprint:
            rec.update(
                exit_code=None,
                stdout="",
                stderr="blocked: structured-tool and sandbox command admission fingerprints disagree",
                blocked=True,
                ended_at=_now(),
                outcome_class="admission_receipt_mismatch",
                expected_admission_fingerprint=expected_admission_fingerprint,
                actual_admission_fingerprint=decision.fingerprint,
            )
            self.commands.append(rec)
            self._record("command", rec)
            return rec
        if not decision.accepted:
            codes = ",".join(decision.reason_codes) or "rejected"
'''
    text = replace_once(text, anchor, insertion, "sandbox fingerprint guard")
    path.write_text(text)


def patch_code_agent() -> None:
    path = Path("local_ui/code_agent.py")
    text = path.read_text()
    if "def _admit_turn_actions(" in text:
        print("CodeAgent already patched")
        return
    text = replace_once(
        text,
        "from typing import Any, Callable, Dict, Iterator, List, Optional\n",
        "from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple\n\n"
        "from lolm.command_admission import (\n"
        "    ExecutionContract,\n"
        "    RiskClass,\n"
        "    admit_tool_call,\n"
        ")\n",
        "CodeAgent admission imports",
    )
    text = replace_once(
        text,
        "        self.actions: List[Dict[str, Any]] = []\n",
        "        self.actions: List[Dict[str, Any]] = []\n"
        "        self._admission_receipts: List[Dict[str, Any]] = []\n",
        "CodeAgent admission state",
    )
    helper = r'''
    def _tool_execution_contract(
        self,
        task: str,
        *,
        source: str = "code_agent.turn",
        timeout: Optional[int] = None,
        risk_class: RiskClass = RiskClass.PROCESS_EXECUTION,
    ) -> ExecutionContract:
        """Compile one deterministic contract for a parsed model tool action."""
        try:
            known = tuple(self.sb.list_files(limit=200))
        except TypeError:
            known = tuple(self.sb.list_files())
        except Exception:
            known = tuple(self._files_written)
        expected: Tuple[str, ...] = tuple()
        verifier = ""
        if self.reliability is not None:
            try:
                expected = tuple(self.reliability.contract.required_paths or ())
            except Exception:
                expected = tuple()
        try:
            verifier = str((self._verify_plan or {}).get("verifier") or "")
        except Exception:
            verifier = ""
        root = str(getattr(self.sb, "dir", "") or "")
        return ExecutionContract(
            task=task or "",
            source=source,
            shell="sh",
            platform="linux",
            cwd=root,
            workspace_root=root,
            primary_language=self._primary_language(),
            known_files=known,
            expected_files=expected,
            timeout_s=int(timeout or self.run_timeout or 120),
            verifier=verifier,
            risk_class=risk_class,
            isolated=bool(self.isolated),
            allow_network=False,
            allow_package_install=False,
        )

    @staticmethod
    def _bounded_admission_value(value: Any) -> Any:
        """Preserve proposal identity without copying full source or secrets."""
        if not isinstance(value, dict):
            return value
        bounded = dict(value)
        for key in ("content", "old", "new"):
            raw = bounded.get(key)
            if isinstance(raw, str):
                encoded = raw.encode("utf-8", "replace")
                bounded[key] = {
                    "bytes": len(encoded),
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "redacted": True,
                }
        return bounded

    def _record_tool_admission(self, decision: Any, *, step: int) -> Dict[str, Any]:
        receipt = decision.to_dict()
        receipt["original"] = self._bounded_admission_value(receipt.get("original"))
        receipt["normalized"] = self._bounded_admission_value(receipt.get("normalized"))
        if isinstance(receipt.get("nested_command"), dict):
            nested = dict(receipt["nested_command"])
            nested["original"] = self._bounded_admission_value(nested.get("original"))
            nested["normalized"] = self._bounded_admission_value(nested.get("normalized"))
            receipt["nested_command"] = nested
        receipt["step"] = int(step)
        self._admission_receipts.append(receipt)
        return receipt

    def _admit_turn_actions(
        self,
        turn: Dict[str, Any],
        task: str,
        step: int,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Any]:
        """Filter one parsed model turn before any tool or command dispatch."""
        filtered = dict(turn or {})
        receipts: List[Dict[str, Any]] = []
        run_decision = None

        def decide(call: Dict[str, Any], risk: RiskClass = RiskClass.PROCESS_EXECUTION):
            decision = admit_tool_call(
                call,
                self._tool_execution_contract(
                    task,
                    timeout=call.get("timeout") if isinstance(call, dict) else None,
                    risk_class=risk,
                ),
            )
            receipts.append(self._record_tool_admission(decision, step=step))
            return decision

        if filtered.get("list"):
            if not decide({"action": "list_files", "limit": 200}, RiskClass.READ_ONLY).accepted:
                filtered["list"] = False

        admitted_reads = []
        for file_path in filtered.get("reads") or []:
            decision = decide({"action": "read_file", "path": file_path}, RiskClass.READ_ONLY)
            if decision.accepted:
                admitted_reads.append(file_path)
        filtered["reads"] = admitted_reads

        admitted_edits = []
        for item in filtered.get("edits") or []:
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                decision = decide({"action": "edit_file"}, RiskClass.WORKSPACE_MUTATION)
            else:
                file_path, old, new = item
                decision = decide(
                    {"action": "edit_file", "path": file_path, "old": old, "new": new},
                    RiskClass.WORKSPACE_MUTATION,
                )
            if decision.accepted:
                admitted_edits.append(tuple(item))
        filtered["edits"] = admitted_edits

        admitted_files = []
        for item in filtered.get("files") or []:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                decision = decide({"action": "write_file"}, RiskClass.WORKSPACE_MUTATION)
            else:
                file_path, content = item
                decision = decide(
                    {"action": "write_file", "path": file_path, "content": content},
                    RiskClass.WORKSPACE_MUTATION,
                )
            if decision.accepted:
                admitted_files.append(tuple(item))
        filtered["files"] = admitted_files

        legacy_file = filtered.get("file")
        if legacy_file:
            if not isinstance(legacy_file, (list, tuple)) or len(legacy_file) != 2:
                decision = decide({"action": "write_file"}, RiskClass.WORKSPACE_MUTATION)
            else:
                file_path, content = legacy_file
                decision = decide(
                    {"action": "write_file", "path": file_path, "content": content},
                    RiskClass.WORKSPACE_MUTATION,
                )
            if not decision.accepted:
                filtered["file"] = None

        command = filtered.get("run")
        if command:
            run_decision = decide(
                {"action": "run", "command": command, "timeout": int(self.run_timeout)},
                RiskClass.PROCESS_EXECUTION,
            )
            if not run_decision.accepted:
                filtered["run"] = None

        if filtered.get("done"):
            finish = decide(
                {"action": "finish", "summary": str(filtered.get("done") or "")},
                RiskClass.READ_ONLY,
            )
            if not finish.accepted:
                filtered["done"] = None

        return filtered, receipts, run_decision

'''
    text = replace_once(
        text,
        "    def _ensure_mutation_gateway(self, task: str) -> Any:\n",
        helper + "    def _ensure_mutation_gateway(self, task: str) -> Any:\n",
        "CodeAgent helper insertion",
    )
    invocation = r'''
            turn, admission_events, run_tool_decision = self._admit_turn_actions(
                turn, task, step,
            )
            rejected_tools = []
            for admission in admission_events:
                yield {"event": "admission_decision", "data": admission}
                if not admission.get("accepted"):
                    rejected_tools.extend(admission.get("reason_codes") or [])
            if rejected_tools:
                reason_text = ", ".join(dict.fromkeys(rejected_tools))
                self._format_nudge = (
                    (self._format_nudge or "")
                    + "\n\nTOOL ADMISSION REJECTED: "
                    + reason_text[:240]
                    + ". Change the tool arguments or strategy; do not repeat the same proposal."
                )

'''
    text = replace_once(
        text,
        '            self._format_nudge = ""\n\n'
        '            # pure DONE → finish (gated on a real, output-producing run)',
        '            self._format_nudge = ""\n' + invocation
        + '            # pure DONE → finish (gated on a real, output-producing run)',
        "CodeAgent turn admission invocation",
    )
    text = replace_once(
        text,
        '        core = {\n            "schema": "lolm.code.receipt.v2",',
        '        admissions = list(getattr(self, "_admission_receipts", [])[-200:])\n'
        '        core = {\n            "schema": "lolm.code.receipt.v2",',
        "CodeAgent receipt prelude",
    )
    text = replace_once(
        text,
        '            "trail": trail[-24:],\n',
        '            "trail": trail[-24:],\n'
        '            "admissions": admissions,\n'
        '            "admission_summary": {\n'
        '                "total": len(admissions),\n'
        '                "admitted": sum(1 for item in admissions if item.get("accepted")),\n'
        '                "rejected": sum(1 for item in admissions if not item.get("accepted")),\n'
        '                "fingerprints": [item.get("fingerprint") for item in admissions if item.get("fingerprint")],\n'
        '            },\n',
        "CodeAgent receipt evidence",
    )
    old_run = '                r = self.sb.run(cmd, timeout=self.run_timeout, isolated=self.isolated)\n'
    new_run = '''                run_context = None
                expected_admission_fingerprint = ""
                if run_tool_decision is not None and (
                    run_tool_decision.normalized.get("command") == cmd
                ):
                    nested = run_tool_decision.nested_command
                    if nested is not None:
                        run_context = nested.contract.to_dict()
                        expected_admission_fingerprint = nested.fingerprint
                r = self.sb.run(
                    cmd,
                    timeout=self.run_timeout,
                    isolated=self.isolated,
                    admission_context=run_context,
                    expected_admission_fingerprint=expected_admission_fingerprint,
                )
                if run_tool_decision is not None and (
                    run_tool_decision.normalized.get("command") == cmd
                ):
                    r["tool_admission_fingerprint"] = run_tool_decision.fingerprint
                    nested = run_tool_decision.nested_command
                    r["tool_command_admission_fingerprint"] = (
                        nested.fingerprint if nested is not None else ""
                    )
                    r["sandbox_admission_fingerprint"] = r.get("admission_fingerprint", "")
                    r["admission_fingerprints_match"] = bool(
                        nested is not None
                        and nested.fingerprint == r.get("admission_fingerprint", "")
                    )
'''
    text = replace_once(text, old_run, new_run, "CodeAgent run binding")
    path.write_text(text)


def patch_tests() -> None:
    path = Path("tests/test_code_agent_admission.py")
    if not path.exists():
        path.write_text(r'''from __future__ import annotations

from pathlib import Path

from local_ui.code_agent import CodeAgent


class StubSandbox:
    def __init__(self, root: Path):
        self.dir = root

    def list_files(self, limit=200):
        return ["main.py"]


def agent(tmp_path: Path) -> CodeAgent:
    instance = CodeAgent.__new__(CodeAgent)
    instance.sb = StubSandbox(tmp_path)
    instance.reliability = None
    instance._files_written = ["main.py"]
    instance._verify_plan = {}
    instance._admission_receipts = []
    instance.run_timeout = 30
    instance.isolated = True
    return instance


def test_turn_compiler_filters_rejected_tools_before_dispatch(tmp_path):
    instance = agent(tmp_path)
    turn = {
        "list": True,
        "reads": ["main.py", "../secret.txt"],
        "edits": [("main.py", "old", "new"), ("../../escape.py", "old", "new")],
        "files": [("helper.py", "print('ok')\n"), ("../escape.py", "print('no')\n")],
        "file": None,
        "run": "xdg-open index.html",
        "done": "finished",
    }
    filtered, receipts, run_decision = instance._admit_turn_actions(turn, "task", 2)
    assert filtered["list"] is True
    assert filtered["reads"] == ["main.py"]
    assert filtered["edits"] == [("main.py", "old", "new")]
    assert filtered["files"] == [("helper.py", "print('ok')\n")]
    assert filtered["run"] is None
    assert filtered["done"] == "finished"
    assert run_decision is not None and run_decision.accepted is False
    assert len(receipts) == 8
    assert any("tool_path_outside_workspace" in item["reason_codes"] for item in receipts)
    assert any("nested_command_rejected" in item["reason_codes"] for item in receipts)


def test_admission_receipts_hash_source_payloads(tmp_path):
    instance = agent(tmp_path)
    secret = "operator-secret-value"
    turn = {"files": [("main.py", secret)], "reads": [], "edits": [], "list": False, "run": None, "done": None}
    filtered, receipts, _ = instance._admit_turn_actions(turn, "task", 1)
    assert filtered["files"] == [("main.py", secret)]
    assert secret not in str(receipts[0])
    content = receipts[0]["normalized"]["content"]
    assert content["redacted"] is True
    assert content["bytes"] == len(secret.encode())
    assert len(content["sha256"]) == 64


def test_safe_run_has_nested_command_receipt(tmp_path):
    instance = agent(tmp_path)
    turn = {"files": [], "reads": [], "edits": [], "list": False, "run": "python3 -m py_compile main.py", "done": None}
    filtered, receipts, run_decision = instance._admit_turn_actions(turn, "task", 3)
    assert filtered["run"] == "python3 -m py_compile main.py"
    assert run_decision is not None and run_decision.accepted is True
    assert run_decision.nested_command is not None
    assert receipts[0]["nested_command"]["accepted"] is True
    assert receipts[0]["step"] == 3


def test_every_structured_action_gets_one_receipt(tmp_path):
    instance = agent(tmp_path)
    turn = {
        "list": True,
        "reads": ["main.py"],
        "edits": [("main.py", "old", "new")],
        "files": [("helper.py", "x = 1\n")],
        "file": ("legacy.py", "x = 2\n"),
        "run": "python3 main.py",
        "done": "complete",
    }
    filtered, receipts, _ = instance._admit_turn_actions(turn, "task", 4)
    assert filtered == turn
    assert len(receipts) == 7
    assert len(instance._admission_receipts) == 7
    assert all(item["schema"] == "lolm.command_admission.v1" for item in receipts)
    assert all(item["fingerprint"] for item in receipts)
''')
    sandbox_tests = Path("tests/test_sandbox.py")
    text = sandbox_tests.read_text()
    if "test_expected_admission_fingerprint_mismatch_fails_before_execution" not in text:
        insertion = '''

def test_expected_admission_fingerprint_mismatch_fails_before_execution(tmp_path, monkeypatch):
    import local_ui.sandbox as sbx

    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not execute")

    monkeypatch.setattr(sbx, "_HAS_BWRAP", False)
    monkeypatch.setattr(sbx.subprocess, "run", forbidden)
    rec = sbx.Sandbox(tmp_path).run(
        "echo safe",
        isolated=False,
        expected_admission_fingerprint="0" * 64,
    )
    assert rec["blocked"] is True
    assert rec["outcome_class"] == "admission_receipt_mismatch"
    assert called is False
'''
        text = replace_once(text, "\ndef test_state_and_destroy(tmp_path):", insertion + "\ndef test_state_and_destroy(tmp_path):", "sandbox binding test insertion")
        sandbox_tests.write_text(text)


def main() -> None:
    patch_sandbox_binding()
    patch_code_agent()
    patch_tests()


if __name__ == "__main__":
    main()
