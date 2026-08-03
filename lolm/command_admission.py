# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Mandatory admission decisions for executable commands and structured tools.

Models and callers may propose commands or tool calls. They never decide whether the
proposal is executable. This module canonicalizes the proposal, validates it against a
typed execution contract, and emits a deterministic receipt before any dispatch.

The decision taxonomy deliberately excludes provider authentication, quota, rate-limit,
and model-generation failures. Those occur before a command proposal exists and must not
be counted as command or model competence failures.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from lolm.command_preflight import ShellDialect, inspect_command, verifier_plan


ADMISSION_SCHEMA = "lolm.command_admission.v1"


class ProposalType(str, Enum):
    COMMAND = "command"
    TOOL = "tool"


class AdmissionOutcome(str, Enum):
    ADMITTED = "admitted"
    COMMAND_POLICY_REJECTION = "command_policy_rejection"
    TOOL_SCHEMA_REJECTION = "tool_schema_rejection"
    ENVIRONMENT_REJECTION = "environment_rejection"


class RiskClass(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_MUTATION = "workspace_mutation"
    PROCESS_EXECUTION = "process_execution"
    NETWORK = "network"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ExecutionContract:
    """Facts required to decide whether a proposal may be dispatched."""

    task: str = ""
    source: str = "unknown"
    shell: ShellDialect | str = ShellDialect.POSIX_SH
    platform: str = "linux"
    cwd: str = ""
    workspace_root: str = ""
    primary_language: str = ""
    known_files: Tuple[str, ...] = field(default_factory=tuple)
    expected_files: Tuple[str, ...] = field(default_factory=tuple)
    timeout_s: int = 120
    verifier: str = ""
    risk_class: RiskClass | str = RiskClass.PROCESS_EXECUTION
    isolated: bool = False
    allow_network: bool = False
    allow_package_install: bool = False

    def normalized_shell(self) -> str:
        if isinstance(self.shell, ShellDialect):
            return self.shell.value
        value = str(self.shell or "sh").strip().lower()
        return {
            "posix": "sh",
            "posix_sh": "sh",
            "/bin/sh": "sh",
            "/bin/bash": "bash",
            "pwsh": "powershell",
            "ps": "powershell",
            "windows": "cmd",
        }.get(value, value)

    def normalized_risk(self) -> str:
        return self.risk_class.value if isinstance(self.risk_class, RiskClass) else str(self.risk_class)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "source": self.source,
            "shell": self.normalized_shell(),
            "platform": str(self.platform or "unknown").lower(),
            "cwd": self.cwd,
            "workspace_root": self.workspace_root,
            "primary_language": self.primary_language,
            "known_files": list(self.known_files),
            "expected_files": list(self.expected_files),
            "timeout_s": self.timeout_s,
            "verifier": self.verifier,
            "risk_class": self.normalized_risk(),
            "isolated": bool(self.isolated),
            "allow_network": bool(self.allow_network),
            "allow_package_install": bool(self.allow_package_install),
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    @property
    def environment_fingerprint(self) -> str:
        return _fingerprint({
            "shell": self.normalized_shell(),
            "platform": str(self.platform or "unknown").lower(),
            "cwd": _normalized_path(self.cwd),
            "workspace_root": _normalized_path(self.workspace_root),
            "isolated": bool(self.isolated),
            "network": bool(self.allow_network),
            "package_install": bool(self.allow_package_install),
        })


@dataclass(frozen=True)
class AdmissionIssue:
    code: str
    message: str
    outcome: AdmissionOutcome
    fatal: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "outcome": self.outcome.value,
            "fatal": self.fatal,
        }


@dataclass(frozen=True)
class AdmissionDecision:
    proposal_type: ProposalType
    original: Any
    normalized: Any
    accepted: bool
    outcome: AdmissionOutcome
    contract: ExecutionContract
    issues: Tuple[AdmissionIssue, ...] = field(default_factory=tuple)
    executable: str = ""
    verifier_plan: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    nested_command: Optional["AdmissionDecision"] = None

    @property
    def reason_codes(self) -> Tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.fatal)

    @property
    def fingerprint(self) -> str:
        return _fingerprint({
            "schema": ADMISSION_SCHEMA,
            "proposal_type": self.proposal_type.value,
            "normalized": self.normalized,
            "accepted": self.accepted,
            "outcome": self.outcome.value,
            "reason_codes": list(self.reason_codes),
            "contract_fingerprint": self.contract.fingerprint,
            "environment_fingerprint": self.contract.environment_fingerprint,
            "executable": self.executable,
            "verifier_plan": list(self.verifier_plan),
            "nested": self.nested_command.fingerprint if self.nested_command else "",
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": ADMISSION_SCHEMA,
            "proposal_type": self.proposal_type.value,
            "original": self.original,
            "normalized": self.normalized,
            "accepted": self.accepted,
            "outcome": self.outcome.value,
            "reason_codes": list(self.reason_codes),
            "issues": [issue.to_dict() for issue in self.issues],
            "executable": self.executable,
            "contract": self.contract.to_dict(),
            "contract_fingerprint": self.contract.fingerprint,
            "environment_fingerprint": self.contract.environment_fingerprint,
            "verifier_plan": list(self.verifier_plan),
            "nested_command": self.nested_command.to_dict() if self.nested_command else None,
            "fingerprint": self.fingerprint,
        }


_DANGEROUS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\brm\s+-rf\s+[/~]",
    r":\(\)\s*\{",
    r"\bsudo\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bchmod\s+-R?\s*777\s+/",
    r">\s*/dev/sd",
    r"\bssh\b",
    r"\bscp\b",
    r"\bsftp\b",
    r"\bnc\s+-",
    r"\bncat\b",
    r"\btelnet\b",
    r"curl[^|]*\|\s*(?:sh|bash)",
    r"wget[^|]*\|\s*(?:sh|bash)",
    r"\bcrontab\b",
    r"/etc/(?:passwd|shadow|sudoers)",
    r"\bsystemctl\b",
    r"\bkillall\b",
    r"\.ssh/",
    r"\bid_(?:rsa|ed25519|ecdsa)\b",
    r"authorized_keys",
    r"\.aws/",
    r"\.npmrc\b",
    r"\.git-credentials\b",
    r"\.kube/",
    r"\.docker/config",
    r"/proc/\d+/environ",
    r"OPERATOR_SECRET|SANDBOX_SECRET|NPM_TOKEN",
))
_NETWORK = re.compile(
    r"(?:^|[;&|]\s*)(?:curl|wget|ssh|scp|sftp|telnet|nc|ncat)\b|"
    r"\bgit\s+(?:clone|fetch|pull|push)\b|"
    r"\b(?:python3?|node)\b[^\n;&|]*(?:https?://|requests\.|urllib\.|fetch\s*\()",
    re.IGNORECASE,
)
_PACKAGE_INSTALL = re.compile(
    r"\b(?:pip(?:3)?\s+install|python(?:3)?\s+-m\s+pip\s+install|"
    r"npm\s+(?:install|i|add)|pnpm\s+(?:install|add)|yarn\s+(?:install|add)|"
    r"apt(?:-get)?\s+install|brew\s+install)\b",
    re.IGNORECASE,
)
_NATURAL_REQUEST = re.compile(
    r"^\s*(?:please\b|could\s+you\b|would\s+you\b|can\s+you\b|"
    r"(?:open|create|write|make|explain|show|tell|fix|verify)\b)",
    re.IGNORECASE,
)
_TRAVERSAL = re.compile(r"(?:^|[\s'\"=])\.\.(?:/|\\)")
_SENSITIVE_ABSOLUTE = re.compile(
    r"(?:^|[\s'\"=])(?:/etc/|/root/|/home/(?![^/]+/(?:work|workspace)\b)|"
    r"[A-Za-z]:\\Users\\[^\\]+\\\.(?:ssh|aws|kube))",
    re.IGNORECASE,
)

_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "run": {
        "required": {"command": str},
        "optional": {"timeout": int},
    },
    "write_file": {
        "required": {"path": str, "content": str},
        "optional": {"reason": str},
    },
    "read_file": {
        "required": {"path": str},
        "optional": {},
    },
    "edit_file": {
        "required": {"path": str, "old": str, "new": str},
        "optional": {"reason": str},
    },
    "write_and_run": {
        "required": {"path": str, "content": str, "command": str},
        "optional": {"timeout": int, "reason": str},
    },
    "list_files": {
        "required": {},
        "optional": {"limit": int},
    },
    "finish": {
        "required": {"summary": str},
        "optional": {},
    },
}


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8", "replace")).hexdigest()


def _normalized_path(value: str) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except Exception:
        return str(value)


def _cwd_issue(contract: ExecutionContract) -> Optional[AdmissionIssue]:
    if not contract.cwd or not contract.workspace_root:
        return None
    try:
        cwd = Path(contract.cwd).expanduser().resolve()
        root = Path(contract.workspace_root).expanduser().resolve()
    except Exception:
        return AdmissionIssue(
            "invalid_execution_path",
            "The working directory or workspace root could not be resolved.",
            AdmissionOutcome.ENVIRONMENT_REJECTION,
        )
    if cwd != root and root not in cwd.parents:
        return AdmissionIssue(
            "cwd_outside_workspace",
            "The requested working directory is outside the admitted workspace root.",
            AdmissionOutcome.ENVIRONMENT_REJECTION,
        )
    return None


def _verifier_receipt(contract: ExecutionContract) -> Tuple[Dict[str, Any], ...]:
    plans = []
    if contract.verifier:
        plans.append({
            "verifier": contract.verifier,
            "command": "",
            "internal": True,
            "evidence_kind": "contract_selected",
        })
    for expected in contract.expected_files:
        for plan in verifier_plan(expected, primary_language=contract.primary_language):
            item = {
                "verifier": plan.verifier,
                "command": plan.command,
                "internal": plan.internal,
                "evidence_kind": plan.evidence_kind,
            }
            if item not in plans:
                plans.append(item)
    return tuple(plans)


def admit_command(command: str, contract: Optional[ExecutionContract] = None) -> AdmissionDecision:
    """Admit or reject one command before execution."""
    contract = contract or ExecutionContract(
        platform=os.name,
        cwd=os.getcwd(),
        workspace_root=os.getcwd(),
    )
    original = "" if command is None else str(command)
    normalized = original.strip()
    issues = []

    cwd_issue = _cwd_issue(contract)
    if cwd_issue:
        issues.append(cwd_issue)
    if not isinstance(contract.timeout_s, int) or not 1 <= contract.timeout_s <= 3600:
        issues.append(AdmissionIssue(
            "invalid_timeout",
            "Command timeout must be an integer between 1 and 3600 seconds.",
            AdmissionOutcome.ENVIRONMENT_REJECTION,
        ))

    if _NATURAL_REQUEST.search(normalized):
        issues.append(AdmissionIssue(
            "natural_language_command",
            "Natural-language instructions are not executable command payloads.",
            AdmissionOutcome.COMMAND_POLICY_REJECTION,
        ))

    preflight = inspect_command(
        normalized,
        shell=contract.shell,
        primary_language=contract.primary_language,
        known_files=contract.known_files,
    )
    for issue in preflight.issues:
        if issue.fatal:
            issues.append(AdmissionIssue(
                issue.code,
                issue.message,
                AdmissionOutcome.COMMAND_POLICY_REJECTION,
            ))

    if any(pattern.search(normalized) for pattern in _DANGEROUS):
        issues.append(AdmissionIssue(
            "dangerous_command",
            "Destructive, privileged, credential, or host-reach command was refused.",
            AdmissionOutcome.COMMAND_POLICY_REJECTION,
        ))
    if _TRAVERSAL.search(normalized):
        issues.append(AdmissionIssue(
            "path_traversal",
            "Command contains a parent-directory traversal token.",
            AdmissionOutcome.COMMAND_POLICY_REJECTION,
        ))
    if _SENSITIVE_ABSOLUTE.search(normalized):
        issues.append(AdmissionIssue(
            "sensitive_absolute_path",
            "Command references a sensitive absolute host path.",
            AdmissionOutcome.COMMAND_POLICY_REJECTION,
        ))
    if not contract.allow_network and _NETWORK.search(normalized):
        issues.append(AdmissionIssue(
            "network_not_admitted",
            "The execution contract does not admit network access.",
            AdmissionOutcome.COMMAND_POLICY_REJECTION,
        ))
    if not contract.allow_package_install and _PACKAGE_INSTALL.search(normalized):
        issues.append(AdmissionIssue(
            "package_install_not_admitted",
            "The execution contract does not admit package installation.",
            AdmissionOutcome.COMMAND_POLICY_REJECTION,
        ))

    # Preserve first-occurrence order while preventing duplicate reason inflation.
    unique = []
    seen = set()
    for issue in issues:
        if issue.code not in seen:
            unique.append(issue)
            seen.add(issue.code)
    accepted = not unique
    outcome = AdmissionOutcome.ADMITTED if accepted else unique[0].outcome
    return AdmissionDecision(
        proposal_type=ProposalType.COMMAND,
        original=original,
        normalized=normalized,
        accepted=accepted,
        outcome=outcome,
        contract=contract,
        issues=tuple(unique),
        executable=preflight.executable,
        verifier_plan=_verifier_receipt(contract),
    )


def _safe_tool_path(value: str) -> Optional[AdmissionIssue]:
    if not value or "\x00" in value:
        return AdmissionIssue(
            "invalid_tool_path",
            "Tool path is empty or contains a NUL byte.",
            AdmissionOutcome.TOOL_SCHEMA_REJECTION,
        )
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return AdmissionIssue(
            "tool_path_outside_workspace",
            "Tool path must be relative and remain inside the workspace.",
            AdmissionOutcome.TOOL_SCHEMA_REJECTION,
        )
    return None


def admit_tool_call(call: Mapping[str, Any], contract: Optional[ExecutionContract] = None) -> AdmissionDecision:
    """Validate and canonicalize one JSON-style tool call before dispatch."""
    contract = contract or ExecutionContract(
        platform=os.name,
        cwd=os.getcwd(),
        workspace_root=os.getcwd(),
    )
    original: Any = dict(call) if isinstance(call, Mapping) else call
    issues = []
    normalized: Dict[str, Any] = {}

    if not isinstance(call, Mapping):
        issues.append(AdmissionIssue(
            "tool_call_not_object",
            "Tool call must be a JSON object.",
            AdmissionOutcome.TOOL_SCHEMA_REJECTION,
        ))
        action = ""
    else:
        action = str(call.get("action") or "").strip().lower()
        if not action:
            issues.append(AdmissionIssue(
                "missing_tool_action",
                "Tool call is missing the action field.",
                AdmissionOutcome.TOOL_SCHEMA_REJECTION,
            ))
        elif action not in _TOOL_SCHEMAS:
            issues.append(AdmissionIssue(
                "unknown_tool_action",
                f"Unknown tool action: {action}",
                AdmissionOutcome.TOOL_SCHEMA_REJECTION,
            ))
        normalized["action"] = action

    nested = None
    schema = _TOOL_SCHEMAS.get(action)
    if schema and isinstance(call, Mapping):
        allowed = {"action", *schema["required"], *schema["optional"]}
        unknown = sorted(str(key) for key in call if key not in allowed)
        if unknown:
            issues.append(AdmissionIssue(
                "unknown_tool_arguments",
                f"Unknown arguments for {action}: {', '.join(unknown)}",
                AdmissionOutcome.TOOL_SCHEMA_REJECTION,
            ))
        for name, expected_type in schema["required"].items():
            if name not in call:
                issues.append(AdmissionIssue(
                    "missing_tool_argument",
                    f"Tool {action} requires argument: {name}",
                    AdmissionOutcome.TOOL_SCHEMA_REJECTION,
                ))
            elif not isinstance(call[name], expected_type):
                issues.append(AdmissionIssue(
                    "invalid_tool_argument_type",
                    f"Tool argument {name} must be {expected_type.__name__}.",
                    AdmissionOutcome.TOOL_SCHEMA_REJECTION,
                ))
            else:
                normalized[name] = call[name]
        for name, expected_type in schema["optional"].items():
            if name in call:
                if not isinstance(call[name], expected_type):
                    issues.append(AdmissionIssue(
                        "invalid_tool_argument_type",
                        f"Tool argument {name} must be {expected_type.__name__}.",
                        AdmissionOutcome.TOOL_SCHEMA_REJECTION,
                    ))
                else:
                    normalized[name] = call[name]

        if "path" in normalized:
            path_issue = _safe_tool_path(normalized["path"])
            if path_issue:
                issues.append(path_issue)
            else:
                normalized["path"] = str(PurePosixPath(normalized["path"].replace("\\", "/")))
        if "timeout" in normalized and not 1 <= normalized["timeout"] <= 3600:
            issues.append(AdmissionIssue(
                "invalid_tool_timeout",
                "Tool timeout must be between 1 and 3600 seconds.",
                AdmissionOutcome.TOOL_SCHEMA_REJECTION,
            ))
        if action in {"run", "write_and_run"} and isinstance(normalized.get("command"), str):
            nested_contract = ExecutionContract(
                **{
                    **contract.__dict__,
                    "timeout_s": normalized.get("timeout", contract.timeout_s),
                    "risk_class": RiskClass.PROCESS_EXECUTION,
                }
            )
            nested = admit_command(normalized["command"], nested_contract)
            if not nested.accepted:
                issues.append(AdmissionIssue(
                    "nested_command_rejected",
                    "The tool's command failed mandatory command admission.",
                    AdmissionOutcome.COMMAND_POLICY_REJECTION,
                ))

    unique = []
    seen = set()
    for issue in issues:
        if issue.code not in seen:
            unique.append(issue)
            seen.add(issue.code)
    accepted = not unique
    if accepted:
        outcome = AdmissionOutcome.ADMITTED
    else:
        command_rejection = next(
            (issue for issue in unique if issue.outcome == AdmissionOutcome.COMMAND_POLICY_REJECTION),
            None,
        )
        outcome = command_rejection.outcome if command_rejection else unique[0].outcome
    return AdmissionDecision(
        proposal_type=ProposalType.TOOL,
        original=original,
        normalized=normalized,
        accepted=accepted,
        outcome=outcome,
        contract=contract,
        issues=tuple(unique),
        executable=nested.executable if nested else "",
        verifier_plan=_verifier_receipt(contract),
        nested_command=nested,
    )
