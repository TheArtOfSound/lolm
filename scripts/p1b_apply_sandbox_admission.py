#!/usr/bin/env python3
"""Apply the reviewed P1-B sandbox admission patch exactly once."""
from __future__ import annotations

from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def patch_sandbox() -> None:
    path = Path("local_ui/sandbox.py")
    text = path.read_text()
    if '"admission": decision.to_dict()' in text:
        print("sandbox already patched")
        return

    text = replace_once(
        text,
        "from typing import Any, Dict, List, Optional\n",
        "from typing import Any, Dict, List, Optional\n\n"
        "from lolm.command_admission import (\n"
        "    AdmissionOutcome,\n"
        "    ExecutionContract,\n"
        "    RiskClass,\n"
        "    admit_command,\n"
        ")\n",
        "sandbox admission import",
    )

    deny_pattern = re.compile(
        r"\n# Commands refused outright.*?_DENY_RE = re\.compile\(\"\|\"\.join\(_DENY\), re\.IGNORECASE\)\n",
        re.S,
    )
    text, count = deny_pattern.subn("\n", text, count=1)
    if count != 1:
        raise SystemExit(f"remove parallel deny list: expected one match, got {count}")

    text = replace_once(
        text,
        '    def run(self, command: str, timeout: int = 120,\n            isolated: Optional[bool] = None) -> Dict[str, Any]:',
        '    def run(self, command: str, timeout: int = 120,\n'
        '            isolated: Optional[bool] = None, *,\n'
        '            admission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:',
        "sandbox run signature",
    )

    old = '''        command = (command or "").strip()
        want_jail = _HAS_BWRAP if isolated is None else bool(isolated)
        rec: Dict[str, Any] = {"id": _id("cmd"), "command": command,
                               "cwd": "/work" if want_jail else str(self.dir),
                               "isolated": want_jail, "started_at": _now()}
        if not command:
            rec.update(exit_code=None, stdout="", stderr="empty command",
                       blocked=True, ended_at=_now())
            return rec
        if isolated and not _HAS_BWRAP:
            rec.update(exit_code=None, stdout="", blocked=True, ended_at=_now(),
                       stderr="isolation required (bwrap) is not available — refusing to "
                              "run un-jailed")
            self.commands.append(rec); self._record("command", rec)
            return rec
        if _DENY_RE.search(command):
            rec.update(exit_code=None, stdout="",
                       stderr="blocked: destructive/exfiltration/privilege command refused",
                       blocked=True, ended_at=_now())
            self.commands.append(rec); self._record("command", rec)
            return rec
'''
    new = '''        command = (command or "").strip()
        want_jail = _HAS_BWRAP if isolated is None else bool(isolated)
        context = dict(admission_context or {})
        shell = context.get("shell") or ("cmd" if os.name == "nt" else "sh")
        contract = ExecutionContract(
            task=str(context.get("task") or ""),
            source=str(context.get("source") or "sandbox.run"),
            shell=shell,
            platform=str(context.get("platform") or os.name),
            cwd=str(context.get("cwd") or self.dir),
            workspace_root=str(context.get("workspace_root") or self.dir),
            primary_language=str(context.get("primary_language") or ""),
            known_files=tuple(context.get("known_files") or self.list_files()),
            expected_files=tuple(context.get("expected_files") or ()),
            timeout_s=int(timeout),
            verifier=str(context.get("verifier") or ""),
            risk_class=context.get("risk_class") or RiskClass.PROCESS_EXECUTION,
            isolated=want_jail,
            allow_network=bool(context.get("allow_network", False)),
            allow_package_install=bool(context.get("allow_package_install", False)),
        )
        decision = admit_command(command, contract)
        rec: Dict[str, Any] = {
            "id": _id("cmd"),
            "command": command,
            "cwd": "/work" if want_jail else str(self.dir),
            "isolated": want_jail,
            "started_at": _now(),
            "admission": decision.to_dict(),
            "admission_fingerprint": decision.fingerprint,
            "outcome_class": decision.outcome.value,
        }
        if not decision.accepted:
            codes = ",".join(decision.reason_codes) or "rejected"
            message = next((issue.message for issue in decision.issues if issue.fatal),
                           "command admission rejected the proposal")
            rec.update(
                exit_code=None,
                stdout="",
                stderr=f"blocked by command admission [{codes}]: {message}",
                blocked=True,
                ended_at=_now(),
            )
            self.commands.append(rec)
            self._record("command", rec)
            return rec
        if isolated and not _HAS_BWRAP:
            rec.update(
                exit_code=None,
                stdout="",
                blocked=True,
                ended_at=_now(),
                outcome_class="infrastructure_rejection",
                stderr="isolation required (bwrap) is not available — refusing to run un-jailed",
            )
            self.commands.append(rec)
            self._record("command", rec)
            return rec
'''
    text = replace_once(text, old, new, "sandbox mandatory admission block")

    text = replace_once(
        text,
        '        return self.run(f"git clone --depth 1 {repo_url} repo", timeout=timeout)',
        '        return self.run(\n'
        '            f"git clone --depth 1 {repo_url} repo",\n'
        '            timeout=timeout,\n'
        '            admission_context={\n'
        '                "source": "sandbox.clone",\n'
        '                "allow_network": True,\n'
        '                "risk_class": RiskClass.NETWORK,\n'
        '            },\n'
        '        )',
        "clone network authority",
    )
    path.write_text(text)


def patch_tests() -> None:
    path = Path("tests/test_sandbox.py")
    text = path.read_text()
    if "test_every_run_has_mandatory_admission_receipt" in text:
        print("sandbox tests already patched")
        return
    insertion = '''

def test_every_run_has_mandatory_admission_receipt(tmp_path):
    sb = Sandbox(tmp_path)
    rec = sb.run("echo admitted")
    assert rec["blocked"] is False
    assert rec["admission"]["schema"] == "lolm.command_admission.v1"
    assert rec["admission"]["accepted"] is True
    assert rec["admission_fingerprint"] == rec["admission"]["fingerprint"]
    assert rec["outcome_class"] == "admitted"


def test_direct_sandbox_calls_cannot_bypass_admission(tmp_path):
    sb = Sandbox(tmp_path)
    cases = {
        "Open index.html in a browser": "natural_language_command",
        "```sh\\necho no\\n```": "markdown_in_command",
        "xdg-open index.html": "desktop_open_unavailable",
        "node --check <(cat app.js)": "process_substitution",
        "cat ../../etc/passwd": "path_traversal",
        "curl https://example.com/data": "network_not_admitted",
        "pip install requests": "package_install_not_admitted",
    }
    for command, reason in cases.items():
        before = len(sb.commands)
        rec = sb.run(command)
        assert rec["blocked"] is True, command
        assert rec["exit_code"] is None
        assert reason in rec["admission"]["reason_codes"]
        assert len(sb.commands) == before + 1


def test_empty_command_is_rejected_and_recorded_by_admission(tmp_path):
    sb = Sandbox(tmp_path)
    rec = sb.run("")
    assert rec["blocked"] is True
    assert "empty_command" in rec["admission"]["reason_codes"]
    assert sb.commands[-1]["admission_fingerprint"] == rec["admission_fingerprint"]


def test_explicit_network_contract_is_visible_in_receipt(tmp_path, monkeypatch):
    import local_ui.sandbox as sbx

    class Completed:
        returncode = 0
        stdout = "cloned"
        stderr = ""

    monkeypatch.setattr(sbx, "_HAS_BWRAP", False)
    monkeypatch.setattr(sbx.subprocess, "run", lambda *args, **kwargs: Completed())
    sb = sbx.Sandbox(tmp_path)
    rec = sb.run(
        "git clone https://github.com/example/repo repo",
        isolated=False,
        admission_context={"source": "test.network", "allow_network": True},
    )
    assert rec["blocked"] is False
    assert rec["admission"]["contract"]["allow_network"] is True
    assert rec["admission"]["accepted"] is True


def test_isolation_failure_is_not_mislabeled_as_command_rejection(tmp_path, monkeypatch):
    import local_ui.sandbox as sbx
    monkeypatch.setattr(sbx, "_HAS_BWRAP", False)
    rec = sbx.Sandbox(tmp_path).run("echo hi", isolated=True)
    assert rec["admission"]["accepted"] is True
    assert rec["outcome_class"] == "infrastructure_rejection"
    assert rec["blocked"] is True
'''
    anchor = "\ndef test_state_and_destroy(tmp_path):"
    text = replace_once(text, anchor, insertion + anchor, "sandbox test insertion")
    path.write_text(text)


def main() -> None:
    patch_sandbox()
    patch_tests()


if __name__ == "__main__":
    main()
