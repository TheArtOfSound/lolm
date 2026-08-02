# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Semantic Failure Ledger (SFL).

Fingerprint = hash(environment_id, capability_id, tool_id, canonical_error_class,
artifact_type, normalized_root_cause, strategy_family).

Equivalent failures merge even when wording changes. After recurrence the next
candidate must alter a causal lever.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

# Map stderr noise → canonical error class
_CANONICAL = [
    (re.compile(r"SyntaxError", re.I), "syntax_error"),
    (re.compile(r"IndentationError", re.I), "indentation_error"),
    (re.compile(r"ModuleNotFoundError|No module named", re.I), "missing_module"),
    (re.compile(r"ImportError", re.I), "import_error"),
    (re.compile(r"NameError", re.I), "name_error"),
    (re.compile(r"AttributeError", re.I), "attribute_error"),
    (re.compile(r"TypeError", re.I), "type_error"),
    (re.compile(r"ValueError", re.I), "value_error"),
    (re.compile(r"AssertionError", re.I), "assertion_error"),
    (re.compile(r"FileNotFoundError|No such file", re.I), "file_not_found"),
    (re.compile(r"ZeroDivisionError", re.I), "zero_division"),
    (re.compile(r"Timeout|timed out|killed", re.I), "timeout"),
    (re.compile(r"xdg-open|no application|cannot open display|no providers", re.I), "desktop_open_unavailable"),
    (re.compile(r"PermissionError|permission denied", re.I), "permission"),
    (re.compile(r"ConnectionError|network is unreachable|Name or service not known", re.I), "network_unavailable"),
    (re.compile(r"NO TESTS RAN|no tests ran", re.I), "no_tests_ran"),
]


def canonical_error_class(stderr: str, stdout: str = "", command: str = "") -> str:
    blob = f"{command}\n{stderr}\n{stdout}"
    for rx, label in _CANONICAL:
        if rx.search(blob):
            return label
    if not (stderr or stdout).strip():
        return "empty_failure"
    # Normalize: strip paths/numbers for residual class
    cleaned = re.sub(r"/[^\s:]+", "<path>", (stderr or stdout)[:200])
    cleaned = re.sub(r"\d+", "N", cleaned)
    return "other:" + hashlib.sha256(cleaned.encode()).hexdigest()[:10]


def normalize_root_cause(
    *,
    error_class: str,
    tool: str = "",
    capability: str = "",
    artifact_type: str = "",
) -> str:
    """Causal root, not lexical stderr."""
    if error_class == "desktop_open_unavailable":
        return "capability_missing:desktop.open"
    if error_class == "network_unavailable":
        return "capability_missing:network.outbound"
    if error_class == "missing_module":
        return "dependency_or_missing_local_module"
    if error_class in ("syntax_error", "indentation_error"):
        return f"artifact_syntax:{artifact_type or 'unknown'}"
    if error_class == "no_tests_ran":
        return "wrong_test_invocation"
    if error_class == "file_not_found":
        return "missing_artifact_path"
    if capability:
        return f"capability:{capability}:{error_class}"
    if tool:
        return f"tool:{tool}:{error_class}"
    return f"error:{error_class}"


# Causal levers a branch/repair must change
CAUSAL_LEVERS = (
    "artifact_schema",
    "implementation_pattern",
    "dependency_plan",
    "tool_plan",
    "verifier_plan",
    "checkpoint_base",
)


@dataclass
class FailureFingerprint:
    fingerprint: str
    environment_id: str
    capability_id: str
    tool_id: str
    canonical_error_class: str
    artifact_type: str
    normalized_root_cause: str
    strategy_family: str
    recurrence: int = 1
    attempted_remediations: List[str] = field(default_factory=list)
    raw_evidence: List[str] = field(default_factory=list)
    first_ts: float = 0.0
    last_ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def make_fingerprint(
    *,
    environment_id: str,
    capability_id: str,
    tool_id: str,
    canonical_error_class: str,
    artifact_type: str,
    normalized_root_cause: str,
    strategy_family: str = "",
) -> str:
    key = "|".join([
        environment_id or "",
        capability_id or "",
        tool_id or "",
        canonical_error_class or "",
        artifact_type or "",
        normalized_root_cause or "",
        strategy_family or "",
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:20]


class SemanticFailureLedger:
    """Structured causal failure memory for a single run (or durable store)."""

    def __init__(self, environment_id: str = "") -> None:
        self.environment_id = environment_id
        self.entries: Dict[str, FailureFingerprint] = {}
        self._order: List[str] = []

    def record(
        self,
        *,
        command: str = "",
        stderr: str = "",
        stdout: str = "",
        exit_code: int = 1,
        tool_id: str = "",
        capability_id: str = "",
        artifact_type: str = "",
        strategy_family: str = "",
        remediation: str = "",
    ) -> FailureFingerprint:
        err_class = canonical_error_class(stderr, stdout, command)
        if not tool_id:
            tool_id = (command or "").split()[0] if command else ""
        if not capability_id:
            if err_class == "desktop_open_unavailable":
                capability_id = "desktop.open"
            elif err_class == "network_unavailable":
                capability_id = "network.outbound"
        root = normalize_root_cause(
            error_class=err_class,
            tool=tool_id,
            capability=capability_id,
            artifact_type=artifact_type,
        )
        fp = make_fingerprint(
            environment_id=self.environment_id,
            capability_id=capability_id,
            tool_id=tool_id,
            canonical_error_class=err_class,
            artifact_type=artifact_type,
            normalized_root_cause=root,
            strategy_family=strategy_family,
        )
        now = time.time()
        if fp in self.entries:
            e = self.entries[fp]
            e.recurrence += 1
            e.last_ts = now
            evidence = (stderr or stdout or command)[:300]
            if evidence and evidence not in e.raw_evidence:
                e.raw_evidence.append(evidence)
            if remediation and remediation not in e.attempted_remediations:
                e.attempted_remediations.append(remediation)
            return e
        e = FailureFingerprint(
            fingerprint=fp,
            environment_id=self.environment_id,
            capability_id=capability_id,
            tool_id=tool_id,
            canonical_error_class=err_class,
            artifact_type=artifact_type,
            normalized_root_cause=root,
            strategy_family=strategy_family,
            recurrence=1,
            attempted_remediations=[remediation] if remediation else [],
            raw_evidence=[(stderr or stdout or command)[:300]],
            first_ts=now,
            last_ts=now,
        )
        self.entries[fp] = e
        self._order.append(fp)
        return e

    def current_root_cause(self) -> Optional[FailureFingerprint]:
        if not self._order:
            return None
        return self.entries[self._order[-1]]

    def is_repeated(self, min_recurrence: int = 2) -> bool:
        cur = self.current_root_cause()
        return bool(cur and cur.recurrence >= min_recurrence)

    def requires_causal_change(self) -> Optional[str]:
        """If repeated, return the lever that must change."""
        cur = self.current_root_cause()
        if not cur or cur.recurrence < 2:
            return None
        # Map root cause → required lever
        root = cur.normalized_root_cause
        if root.startswith("capability_missing"):
            return "verifier_plan"
        if root.startswith("artifact_syntax"):
            return "implementation_pattern"
        if root == "missing_artifact_path":
            return "artifact_schema"
        if root == "dependency_or_missing_local_module":
            return "dependency_plan"
        if root == "wrong_test_invocation":
            return "tool_plan"
        return "implementation_pattern"

    def strategy_allowed(self, strategy_family: str, changed_levers: Sequence[str]) -> bool:
        """Reject strategies that do not alter a causal lever after recurrence."""
        req = self.requires_causal_change()
        if req is None:
            return True
        if not changed_levers:
            return False
        return req in changed_levers or any(l in CAUSAL_LEVERS for l in changed_levers)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
            "order": list(self._order),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SemanticFailureLedger":
        led = cls(environment_id=(d or {}).get("environment_id") or "")
        for k, v in ((d or {}).get("entries") or {}).items():
            known = {f.name for f in FailureFingerprint.__dataclass_fields__.values()}  # type: ignore
            led.entries[k] = FailureFingerprint(**{a: b for a, b in v.items() if a in known})
        led._order = list((d or {}).get("order") or [])
        return led
