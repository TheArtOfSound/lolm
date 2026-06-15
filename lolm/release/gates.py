# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Proof gates — the deterministic checks that authorise an autonomous ship.

Three gates, each a list of named boolean checks with evidence:
  MergeGate    — may the daily branch merge to main?
  PublishGate  — may the npm package publish (canary first, then stable)?
  DeployGate   — may production deploy?

Plus two safety scanners that run on the diff regardless of the rest:
  secret_scan            — refuse if the change adds a key/token/credential.
  protected_files_touched — refuse if a protected cred/signing/secret path changed.

A gate passes ONLY if every check passes. The blockers list names exactly what
failed and quotes the failing command, so a blocked run is self-explaining.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""
    command: str = ""
    output_tail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail,
                "command": self.command, "output_tail": self.output_tail[-600:]}


# ── safety scanners ──────────────────────────────────────────────────────────
# Lines that ADD a secret (diff '+' lines) — high-confidence patterns only.
_SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"(?i)aws_secret_access_key\s*=\s*['\"]?[A-Za-z0-9/+=]{40}", "AWS secret key"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "private key block"),
    (r"(?i)(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "hardcoded credential"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI-style secret key"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal token"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"npm_[A-Za-z0-9]{36}", "npm token"),
]
# Allow obvious placeholders so we don't block on documentation/examples.
_PLACEHOLDER = re.compile(r"(?i)(your[_-]?|example|placeholder|xxxx|<[a-z_]+>|\$\{?[A-Z_]+\}?|env\.|process\.env|os\.environ)")


def secret_scan(diff_text: str) -> GateResult:
    """Scan added diff lines for real secrets. Passes when none are introduced."""
    hits: List[str] = []
    for line in (diff_text or "").splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        # Honor an explicit inline allowlist (the detect-secrets convention) so
        # intentional test fixtures / examples don't block a real ship.
        if "pragma: allowlist secret" in body or "noqa: secret" in body:
            continue
        for pat, label in _SECRET_PATTERNS:
            for m in re.finditer(pat, body):
                seg = m.group(0)
                if _PLACEHOLDER.search(seg):   # the matched secret is itself a placeholder
                    continue
                hits.append(f"{label}: {seg.strip()[:60]}")
    return GateResult("no_secret_introduced", not hits,
                      "clean" if not hits else f"{len(hits)} possible secret(s): " + "; ".join(hits[:3]))


# Paths the agent must never modify autonomously.
_PROTECTED = [
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"\.pem$"), re.compile(r"\.key$"), re.compile(r"_rsa$"),
    re.compile(r"(^|/)secrets?(/|\.|$)"),
    re.compile(r"(^|/)deploy/.*(secret|credential|key)", re.IGNORECASE),
    re.compile(r"signing[_-]?key", re.IGNORECASE),
    re.compile(r"(^|/)id_ed25519"),
    re.compile(r"\.npmrc$"), re.compile(r"(^|/)\.ssh/"),
]


def protected_files_touched(changed_files: Sequence[str]) -> GateResult:
    bad = [f for f in (changed_files or []) if any(p.search(f) for p in _PROTECTED)]
    return GateResult("no_protected_file_touched", not bad,
                      "clean" if not bad else "touched: " + ", ".join(bad[:5]))


# ── gates ────────────────────────────────────────────────────────────────────
@dataclass
class _BaseGate:
    checks: List[GateResult] = field(default_factory=list)

    def add(self, result: GateResult) -> "GateResult":
        self.checks.append(result)
        return result

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def blockers(self) -> List[str]:
        return [f"{c.name}: {c.detail}" + (f" [{c.command}]" if c.command else "")
                for c in self.checks if not c.passed]

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "blockers": self.blockers,
                "checks": [c.to_dict() for c in self.checks]}


class MergeGate(_BaseGate):
    """May the daily branch merge to main? (typecheck, lint, tests, build, evals,
    security, secret-scan, protected-files, receipt, rollback)."""

    REQUIRED = ("typecheck", "lint", "tests", "build", "evals",
                "security_no_high_critical", "no_secret_introduced",
                "no_protected_file_touched", "receipt_generated", "rollback_available")

    def missing(self) -> List[str]:
        have = {c.name for c in self.checks}
        return [r for r in self.REQUIRED if r not in have]

    @property
    def passed(self) -> bool:
        return not self.missing() and super().passed


class PublishGate(_BaseGate):
    """May npm publish? (build, tests, evals, version_bumped, changelog,
    provenance_enabled, contents_inspected, no_private_files, canary_smoke)."""

    REQUIRED = ("build", "tests", "evals", "version_bumped", "changelog_generated",
                "provenance_enabled", "package_contents_inspected",
                "no_private_files_included", "canary_smoke_passed")

    def missing(self) -> List[str]:
        have = {c.name for c in self.checks}
        return [r for r in self.REQUIRED if r not in have]

    @property
    def passed(self) -> bool:
        return not self.missing() and super().passed


class DeployGate(_BaseGate):
    """May production deploy? (prod_build, smoke, health, critical_routes,
    lolm_demo_route, receipt_route, rollback_available)."""

    REQUIRED = ("prod_build", "smoke_tests", "health_endpoint", "critical_routes",
                "lolm_demo_route", "receipt_route", "rollback_available")

    def missing(self) -> List[str]:
        have = {c.name for c in self.checks}
        return [r for r in self.REQUIRED if r not in have]

    @property
    def passed(self) -> bool:
        return not self.missing() and super().passed


def evaluate_gates(*gates: _BaseGate) -> Dict[str, Any]:
    """Aggregate: pass only if every supplied gate passes; collect all blockers."""
    blockers: List[str] = []
    for g in gates:
        miss = getattr(g, "missing", lambda: [])()
        blockers += [f"{g.__class__.__name__}: missing check '{m}'" for m in miss]
        blockers += [f"{g.__class__.__name__}: {b}" for b in g.blockers]
    return {"passed": not blockers, "blockers": blockers}
