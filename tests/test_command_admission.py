from __future__ import annotations

import json

import pytest

from lolm.command_admission import (
    ADMISSION_SCHEMA,
    AdmissionOutcome,
    ExecutionContract,
    ProposalType,
    RiskClass,
    admit_command,
    admit_tool_call,
)
from lolm.command_preflight import ShellDialect


def contract(**overrides):
    values = {
        "task": "verify the workspace",
        "source": "test",
        "shell": ShellDialect.POSIX_SH,
        "platform": "linux",
        "cwd": "/tmp/workspace",
        "workspace_root": "/tmp/workspace",
        "primary_language": "python",
        "known_files": ("main.py",),
        "expected_files": ("main.py",),
        "timeout_s": 30,
        "verifier": "python.compile",
        "risk_class": RiskClass.PROCESS_EXECUTION,
        "isolated": True,
        "allow_network": False,
        "allow_package_install": False,
    }
    values.update(overrides)
    return ExecutionContract(**values)


def test_admitted_command_has_complete_stable_receipt():
    decision = admit_command("python3 -m py_compile main.py", contract())
    assert decision.accepted is True
    assert decision.outcome == AdmissionOutcome.ADMITTED
    assert decision.proposal_type == ProposalType.COMMAND
    receipt = decision.to_dict()
    assert receipt["schema"] == ADMISSION_SCHEMA
    assert receipt["normalized"] == "python3 -m py_compile main.py"
    assert receipt["executable"] == "python3"
    assert receipt["contract_fingerprint"]
    assert receipt["environment_fingerprint"]
    assert receipt["fingerprint"]
    assert receipt["verifier_plan"][0]["verifier"] == "python.compile"
    assert decision.fingerprint == admit_command(
        "python3 -m py_compile main.py", contract()
    ).fingerprint
    json.dumps(receipt)


@pytest.mark.parametrize("command,reason", [
    ("Open index.html in a browser", "natural_language_command"),
    ("```sh\npython3 main.py\n```", "markdown_in_command"),
    ("xdg-open index.html", "desktop_open_unavailable"),
    ("python3 -c \"print('x')", "unbalanced_shell_quoting"),
    ("node --check <(cat app.js)", "process_substitution"),
    ("rm -rf /", "dangerous_command"),
    ("cat ../../etc/passwd", "path_traversal"),
    ("sudo cat /etc/shadow", "dangerous_command"),
    ("curl https://example.com/data", "network_not_admitted"),
    ("pip install requests", "package_install_not_admitted"),
])
def test_command_policy_rejections(command, reason):
    decision = admit_command(command, contract())
    assert decision.accepted is False
    assert decision.outcome == AdmissionOutcome.COMMAND_POLICY_REJECTION
    assert reason in decision.reason_codes


def test_network_and_package_install_require_explicit_contract_authority():
    network = admit_command(
        "git clone https://github.com/a/b repo",
        contract(allow_network=True),
    )
    assert network.accepted is True
    package = admit_command(
        "python3 -m pip install wheel",
        contract(allow_package_install=True),
    )
    assert package.accepted is True


def test_environment_rejections_are_not_command_competence_failures():
    outside = admit_command(
        "echo ok",
        contract(cwd="/tmp/other", workspace_root="/tmp/workspace"),
    )
    assert outside.accepted is False
    assert outside.outcome == AdmissionOutcome.ENVIRONMENT_REJECTION
    assert outside.reason_codes == ("cwd_outside_workspace",)

    timeout = admit_command("echo ok", contract(timeout_s=0))
    assert timeout.accepted is False
    assert timeout.outcome == AdmissionOutcome.ENVIRONMENT_REJECTION
    assert timeout.reason_codes == ("invalid_timeout",)


def test_shell_dialect_is_part_of_the_contract_and_receipt():
    posix = admit_command("[[ -f main.py ]]", contract(shell=ShellDialect.POSIX_SH))
    bash = admit_command("[[ -f main.py ]]", contract(shell=ShellDialect.BASH))
    assert posix.accepted is False
    assert bash.accepted is True
    assert posix.contract.environment_fingerprint != bash.contract.environment_fingerprint


@pytest.mark.parametrize("call,reason", [
    ("run", "tool_call_not_object"),
    ({}, "missing_tool_action"),
    ({"action": "launch_missiles"}, "unknown_tool_action"),
    ({"action": "run"}, "missing_tool_argument"),
    ({"action": "run", "command": 42}, "invalid_tool_argument_type"),
    ({"action": "run", "command": "echo ok", "surprise": True}, "unknown_tool_arguments"),
    ({"action": "write_file", "path": "../escape.py", "content": "x"}, "tool_path_outside_workspace"),
    ({"action": "read_file", "path": "/etc/passwd"}, "tool_path_outside_workspace"),
    ({"action": "list_files", "limit": 0}, "invalid_tool_timeout"),
])
def test_tool_schema_rejections(call, reason):
    decision = admit_tool_call(call, contract())
    assert decision.accepted is False
    assert reason in decision.reason_codes


def test_tool_limit_zero_is_type_valid_not_timeout():
    # list limits are schema values, not command timeouts. A later dispatcher may clamp.
    decision = admit_tool_call({"action": "list_files", "limit": 0}, contract())
    assert decision.accepted is True


def test_run_tool_contains_nested_command_decision():
    decision = admit_tool_call(
        {"action": "run", "command": "python3 -m py_compile main.py", "timeout": 20},
        contract(),
    )
    assert decision.accepted is True
    assert decision.nested_command is not None
    assert decision.nested_command.accepted is True
    receipt = decision.to_dict()
    assert receipt["nested_command"]["accepted"] is True
    assert receipt["normalized"] == {
        "action": "run",
        "command": "python3 -m py_compile main.py",
        "timeout": 20,
    }


def test_run_tool_cannot_bypass_command_policy():
    decision = admit_tool_call(
        {"action": "run", "command": "xdg-open index.html"},
        contract(primary_language="html", expected_files=("index.html",)),
    )
    assert decision.accepted is False
    assert decision.outcome == AdmissionOutcome.COMMAND_POLICY_REJECTION
    assert "nested_command_rejected" in decision.reason_codes
    assert decision.nested_command is not None
    assert "desktop_open_unavailable" in decision.nested_command.reason_codes


def test_write_and_run_validates_path_and_command_as_one_admission():
    accepted = admit_tool_call({
        "action": "write_and_run",
        "path": "src/main.py",
        "content": "print('ok')\n",
        "command": "python3 src/main.py",
        "timeout": 20,
    }, contract(known_files=("src/main.py",), expected_files=("src/main.py",)))
    assert accepted.accepted is True
    assert accepted.normalized["path"] == "src/main.py"

    rejected = admit_tool_call({
        "action": "write_and_run",
        "path": "../main.py",
        "content": "print('ok')\n",
        "command": "python3 ../main.py",
    }, contract())
    assert rejected.accepted is False
    assert "tool_path_outside_workspace" in rejected.reason_codes
    assert "nested_command_rejected" in rejected.reason_codes


def test_500_distinct_adversarial_commands_are_rejected_before_dispatch():
    cases = []
    for index in range(100):
        cases.append(f"Please open artifact-{index}.html in a browser")
        cases.append(f"```sh\npython3 script-{index}.py\n```")
        cases.append(f"cat ../../secret-{index}.txt")
        cases.append(f"xdg-open page-{index}.html")
        cases.append(f"node --check <(cat script-{index}.js)")
    assert len(cases) == 500
    fingerprints = set()
    for command in cases:
        decision = admit_command(command, contract())
        assert decision.accepted is False, command
        assert decision.outcome == AdmissionOutcome.COMMAND_POLICY_REJECTION
        fingerprints.add(decision.fingerprint)
    assert len(fingerprints) == 500


def test_tool_decision_fingerprint_changes_with_arguments_but_not_mapping_order():
    first = admit_tool_call({
        "action": "write_file",
        "path": "main.py",
        "content": "print(1)\n",
    }, contract())
    reordered = admit_tool_call({
        "content": "print(1)\n",
        "path": "main.py",
        "action": "write_file",
    }, contract())
    changed = admit_tool_call({
        "action": "write_file",
        "path": "main.py",
        "content": "print(2)\n",
    }, contract())
    assert first.accepted and reordered.accepted and changed.accepted
    assert first.fingerprint == reordered.fingerprint
    assert first.fingerprint != changed.fingerprint
