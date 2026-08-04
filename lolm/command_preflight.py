# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Deterministic preflight for model-generated commands.

Language models are allowed to *propose* commands. They are not allowed to decide
whether a string is executable, compatible with the sandbox shell, or suitable
for the artifact under construction. This module performs that decision before
execution and supplies a stable failure taxonomy for repair routing.

The current sandbox executes through ``/bin/sh -c``. Accepting Bash syntax or
human prose and hoping the shell explains the mistake wastes steps and teaches
the repair loop the wrong lesson. Preflight failures are therefore evidence, not
ordinary command failures.
"""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable, List, Optional, Sequence, Tuple


class ShellDialect(str, Enum):
    POSIX_SH = "sh"
    BASH = "bash"
    POWERSHELL = "powershell"
    CMD = "cmd"


class FailureClass(str, Enum):
    NONE = "none"
    FORMAT = "format"
    NATURAL_LANGUAGE = "natural_language"
    SHELL_DIALECT = "shell_dialect"
    DESKTOP_CAPABILITY = "desktop_capability"
    CROSS_LANGUAGE = "cross_language"
    MISSING_EXECUTABLE = "missing_executable"
    COMMAND_SYNTAX = "command_syntax"
    SOURCE_SYNTAX = "source_syntax"
    IMPORT = "import"
    TEST = "test"
    ASSERTION = "assertion"
    RUNTIME = "runtime"
    TIMEOUT = "timeout"
    SECURITY_BLOCK = "security_block"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandIssue:
    code: str
    message: str
    failure_class: FailureClass
    fatal: bool = True
    suggestion: str = ""


@dataclass(frozen=True)
class CommandPreflight:
    command: str
    accepted: bool
    dialect: ShellDialect
    executable: str = ""
    issues: Tuple[CommandIssue, ...] = field(default_factory=tuple)

    @property
    def primary_failure(self) -> FailureClass:
        for issue in self.issues:
            if issue.fatal:
                return issue.failure_class
        return FailureClass.NONE

    @property
    def fingerprint(self) -> str:
        payload = "|".join(
            [self.dialect.value, self.executable]
            + [f"{i.code}:{i.failure_class.value}:{int(i.fatal)}" for i in self.issues]
        )
        return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "accepted": self.accepted,
            "dialect": self.dialect.value,
            "executable": self.executable,
            "primary_failure": self.primary_failure.value,
            "fingerprint": self.fingerprint,
            "issues": [
                {
                    "code": i.code,
                    "message": i.message,
                    "failure_class": i.failure_class.value,
                    "fatal": i.fatal,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
        }


@dataclass(frozen=True)
class VerifierPlan:
    verifier: str
    command: str = ""
    internal: bool = False
    evidence_kind: str = ""


_NATURAL_LANGUAGE_PREFIX = re.compile(
    r"^\s*(?:please\s+)?(?:open|execute|run|use|try|launch|check)\s+"
    r"(?:the\s+|this\s+|that\s+|`|\"|'|index\.html\s+in\s+a\s+web\s+browser)",
    re.IGNORECASE,
)
_DESKTOP_OPEN = re.compile(
    r"^\s*(?:xdg-open|gio\s+open|open|start)\b",
    re.IGNORECASE,
)
_MARKDOWN_FENCE = re.compile(r"```|^\s*`[^`]+`\s*$", re.MULTILINE)
_PROCESS_SUBSTITUTION = re.compile(r"(?:<|>)\(")
_DOUBLE_BRACKET = re.compile(r"(?:^|[;&|\s])\[\[")
_SOURCE_BUILTIN = re.compile(r"(?:^|[;&|]\s*)source\s+")
_BASH_FUNCTION = re.compile(r"(?:^|[;&|]\s*)function\s+[A-Za-z_][A-Za-z0-9_]*")
_BASH_ARRAY = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*=\([^)]*")
_BASH_REDIRECT = re.compile(r"(?:^|\s)&>")
_PYTHON_HTML = re.compile(
    r"\bpython(?:3(?:\.\d+)?)?\b[^\n;&|]*\.(?:html?|css)\b",
    re.IGNORECASE,
)
_PYCOMPILE_NONPY = re.compile(
    r"\bpy_compile\b[^\n;&|]*\.(?:html?|css|js|mjs|cjs|ts|tsx|jsx)\b",
    re.IGNORECASE,
)


def _dialect(value: str | ShellDialect) -> ShellDialect:
    if isinstance(value, ShellDialect):
        return value
    normalized = (value or "sh").strip().lower()
    aliases = {
        "posix": ShellDialect.POSIX_SH,
        "posix_sh": ShellDialect.POSIX_SH,
        "/bin/sh": ShellDialect.POSIX_SH,
        "/bin/bash": ShellDialect.BASH,
        "pwsh": ShellDialect.POWERSHELL,
        "ps": ShellDialect.POWERSHELL,
        "windows": ShellDialect.CMD,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return ShellDialect(normalized)
    except ValueError:
        return ShellDialect.POSIX_SH


def _first_executable(command: str) -> str:
    """Best-effort first executable extraction.

    Environment assignments and a leading ``cd ... &&`` are ignored. This is
    diagnostic only; the sandbox remains the security boundary.
    """
    text = command.strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text, posix=True)
    except ValueError:
        return ""
    idx = 0
    while idx < len(parts) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parts[idx]):
        idx += 1
    if idx >= len(parts):
        return ""
    if parts[idx] == "cd":
        try:
            idx = parts.index("&&", idx + 1) + 1
        except ValueError:
            return "cd"
    return PurePosixPath(parts[idx]).name if idx < len(parts) else ""


def inspect_command(
    command: str,
    *,
    shell: str | ShellDialect = ShellDialect.POSIX_SH,
    primary_language: str = "",
    known_files: Optional[Sequence[str]] = None,
) -> CommandPreflight:
    """Return whether a model-proposed command is structurally executable.

    This intentionally rejects only high-confidence defects. Unknown project
    executables are left to the sandbox because a strict executable allow-list
    would block legitimate repository scripts.
    """
    cmd = (command or "").strip()
    dialect = _dialect(shell)
    issues: List[CommandIssue] = []

    if not cmd:
        issues.append(CommandIssue(
            "empty_command",
            "The model proposed an empty command.",
            FailureClass.FORMAT,
            suggestion="Emit a typed verifier or a concrete executable command.",
        ))
        return CommandPreflight(cmd, False, dialect, "", tuple(issues))

    if _MARKDOWN_FENCE.search(cmd):
        issues.append(CommandIssue(
            "markdown_in_command",
            "Markdown fencing/backticks are not executable shell syntax.",
            FailureClass.FORMAT,
            suggestion="Return only the command string, without Markdown.",
        ))

    if _NATURAL_LANGUAGE_PREFIX.search(cmd):
        issues.append(CommandIssue(
            "natural_language_command",
            "The command is an instruction to a human, not a shell command.",
            FailureClass.NATURAL_LANGUAGE,
            suggestion="Choose a deterministic verifier instead of asking a human to open or inspect the artifact.",
        ))

    if _DESKTOP_OPEN.search(cmd):
        issues.append(CommandIssue(
            "desktop_open_unavailable",
            "Desktop opener commands are unavailable in the headless sandbox.",
            FailureClass.DESKTOP_CAPABILITY,
            suggestion="Use html.render or html.static_lint for browser artifacts.",
        ))

    language = (primary_language or "").strip().lower()
    if _PYTHON_HTML.search(cmd) or _PYCOMPILE_NONPY.search(cmd):
        issues.append(CommandIssue(
            "cross_language_execution",
            "Python was asked to execute or compile a non-Python artifact.",
            FailureClass.CROSS_LANGUAGE,
            suggestion="Select a verifier that matches the artifact language.",
        ))
    elif language == "html" and re.search(r"\bpython(?:3)?\b", cmd) and known_files:
        non_harness_py = [p for p in known_files if p.endswith(".py") and not p.startswith("_lolm_")]
        if not non_harness_py:
            issues.append(CommandIssue(
                "python_on_html_primary",
                "The task is HTML-primary and has no Python harness requiring execution.",
                FailureClass.CROSS_LANGUAGE,
                suggestion="Use html.render, html.static_lint, or JavaScript syntax verification.",
            ))

    if dialect == ShellDialect.POSIX_SH:
        bashisms = (
            (_PROCESS_SUBSTITUTION, "process_substitution", "Process substitution <(...) is a Bash feature.",
             "Write intermediate output to a temporary file, then pass that file to the verifier."),
            (_DOUBLE_BRACKET, "double_bracket", "[[ ... ]] is not portable /bin/sh syntax.",
             "Use POSIX [ ... ] or select bash explicitly."),
            (_SOURCE_BUILTIN, "source_builtin", "source is not a POSIX /bin/sh builtin.",
             "Use `. path/to/file` or select bash explicitly."),
            (_BASH_FUNCTION, "bash_function", "The `function name` form is Bash-specific.",
             "Use `name() { ...; }` or select bash explicitly."),
            (_BASH_ARRAY, "bash_array", "Shell arrays are Bash-specific.",
             "Use positional parameters/files or select bash explicitly."),
            (_BASH_REDIRECT, "bash_redirect", "&> redirection is Bash-specific.",
             "Use `>file 2>&1` or select bash explicitly."),
        )
        for pattern, code, message, suggestion in bashisms:
            if pattern.search(cmd):
                issues.append(CommandIssue(
                    code,
                    message,
                    FailureClass.SHELL_DIALECT,
                    suggestion=suggestion,
                ))

    try:
        shlex.split(cmd, posix=dialect != ShellDialect.CMD)
    except ValueError as exc:
        issues.append(CommandIssue(
            "unbalanced_shell_quoting",
            f"The command has invalid shell quoting: {exc}",
            FailureClass.COMMAND_SYNTAX,
            suggestion="Regenerate the command from structured arguments rather than repairing quotes ad hoc.",
        ))

    executable = _first_executable(cmd)
    accepted = not any(issue.fatal for issue in issues)
    return CommandPreflight(cmd, accepted, dialect, executable, tuple(issues))


def verifier_plan(path: str, *, primary_language: str = "") -> Tuple[VerifierPlan, ...]:
    """Return deterministic verifier choices ordered strongest-first."""
    p = (path or "").lower()
    language = (primary_language or "").lower()
    suffix = PurePosixPath(p).suffix

    if language == "html" or suffix in {".html", ".htm"}:
        return (
            VerifierPlan("html.render", internal=True, evidence_kind="rendered_dom"),
            VerifierPlan("html.static_lint", internal=True, evidence_kind="html_ast"),
            VerifierPlan("javascript.syntax", internal=True, evidence_kind="script_ast"),
        )
    if language in {"javascript", "js"} or suffix in {".js", ".mjs", ".cjs"}:
        return (VerifierPlan("javascript.syntax", f"node --check {shlex.quote(path)}", False, "syntax"),)
    if language in {"typescript", "ts"} or suffix in {".ts", ".tsx"}:
        return (VerifierPlan("typescript.syntax", internal=True, evidence_kind="typescript_ast"),)
    if language == "python" or suffix == ".py":
        return (VerifierPlan("python.compile", f"python3 -m py_compile {shlex.quote(path)}", False, "syntax"),)
    if suffix == ".json":
        return (VerifierPlan("json.parse", internal=True, evidence_kind="parsed_json"),)
    if suffix in {".yaml", ".yml"}:
        return (VerifierPlan("yaml.parse", internal=True, evidence_kind="parsed_yaml"),)
    return (VerifierPlan("artifact.exists", internal=True, evidence_kind="existence"),)


def classify_failure(
    *,
    command: str = "",
    exit_code: Optional[int] = None,
    stdout: str = "",
    stderr: str = "",
    blocked: bool = False,
    preflight: Optional[CommandPreflight] = None,
) -> Tuple[FailureClass, str]:
    """Map execution evidence to a stable root-cause class and fingerprint."""
    if preflight is not None and not preflight.accepted:
        cls = preflight.primary_failure
        return cls, f"preflight:{preflight.fingerprint}"
    text = f"{stderr}\n{stdout}".lower()
    if blocked:
        cls = FailureClass.SECURITY_BLOCK
    elif exit_code == 124 or "timed out" in text or "timeout after" in text:
        cls = FailureClass.TIMEOUT
    elif "not found" in text or "no such file or directory" in text:
        cls = FailureClass.MISSING_EXECUTABLE
    elif "syntax error" in text and any(s in text for s in ("unexpected", "/bin/sh", "shell")):
        cls = FailureClass.SHELL_DIALECT
    elif "syntaxerror" in text or "parse error" in text:
        cls = FailureClass.SOURCE_SYNTAX
    elif "modulenotfounderror" in text or "importerror" in text or "cannot find module" in text:
        cls = FailureClass.IMPORT
    elif "assertionerror" in text or "assertion failed" in text:
        cls = FailureClass.ASSERTION
    elif any(s in text for s in ("failed", "failures", "tests failed", "test failed")):
        cls = FailureClass.TEST
    elif exit_code not in (None, 0):
        cls = FailureClass.RUNTIME
    else:
        cls = FailureClass.NONE
    normalized = re.sub(r"\b0x[0-9a-f]+\b|\b\d+\b", "#", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()[:500]
    payload = f"{cls.value}|{command[:160]}|{normalized}"
    fingerprint = hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:16]
    return cls, fingerprint
