# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The daily release receipt — JSON + markdown, with an unambiguous verdict.

Every daily run ends in exactly one verdict (never a vague "success"):

  shipped_to_main · shipped_to_npm_canary · shipped_to_npm_stable · deployed_live
  blocked_by_tests · blocked_by_evals · blocked_by_security · blocked_by_publish
  blocked_by_deploy · no_change_needed

The receipt records what was learned, what changed, every gate result, the version
delta, the publish/deploy outcomes, the blockers, and the rollback command — so the
run is auditable and reversible without trusting the agent's word.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

VERDICTS = (
    "shipped_to_main", "shipped_to_npm_canary", "shipped_to_npm_stable",
    "deployed_live", "blocked_by_tests", "blocked_by_evals", "blocked_by_security",
    "blocked_by_publish", "blocked_by_deploy", "no_change_needed",
    "ready_gates_passed_not_fired",
)


def _attempted(step: Optional[Dict[str, Any]]) -> bool:
    """A step counts only if it was actually attempted — a skipped (not-fired)
    step is not a failure, so it must not read as blocked_by_*."""
    return bool(step) and not step.get("skipped")


def compute_verdict(*, changed: bool, gates: Dict[str, Any],
                    merged: bool, canary: Optional[Dict[str, Any]],
                    stable: Optional[Dict[str, Any]], deployed: Optional[Dict[str, Any]],
                    blockers: List[str], fire: bool = True) -> str:
    """Pick the single most-advanced state actually reached, else the blocking
    reason. In shadow mode (fire=False) a green run that fired nothing is
    `ready_gates_passed_not_fired` — never a fake `shipped_*`."""
    if not changed and not blockers:
        return "no_change_needed"
    b = " ".join(blockers).lower()
    gates_pass = bool(gates.get("passed", True)) and not blockers
    # Gate failure → the specific blocking reason.
    if not gates_pass:
        if "test" in b:
            return "blocked_by_tests"
        if "eval" in b:
            return "blocked_by_evals"
        if "secret" in b or "security" in b or "protected" in b:
            return "blocked_by_security"
        if "deploy" in b:
            return "blocked_by_deploy"
        if "publish" in b or "npm" in b:
            return "blocked_by_publish"
        return "blocked_by_tests"
    # Gates passed → highest step actually attempted.
    if _attempted(deployed):
        return "deployed_live" if deployed.get("ok") else "blocked_by_deploy"
    if _attempted(stable):
        return "shipped_to_npm_stable" if stable.get("ok") else "blocked_by_publish"
    if _attempted(canary):
        return "shipped_to_npm_canary" if canary.get("ok") else "blocked_by_publish"
    if merged:
        return "shipped_to_main"
    # Green, but nothing fired (shadow / fire disabled).
    return "ready_gates_passed_not_fired"


@dataclass
class DailyReceipt:
    run_id: str
    date: str
    branch: str = ""
    commit: str = ""
    learning_sources_checked: List[str] = field(default_factory=list)
    hf_datasets_scanned: int = 0
    web_searches_performed: int = 0
    memories_written: int = 0
    improvement_targets: List[Dict[str, Any]] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    tests: Dict[str, Any] = field(default_factory=dict)
    evals_before: Dict[str, Any] = field(default_factory=dict)
    evals_after: Dict[str, Any] = field(default_factory=dict)
    build: Dict[str, Any] = field(default_factory=dict)
    gates: Dict[str, Any] = field(default_factory=dict)
    npm_version_before: str = ""
    npm_version_after: str = ""
    canary_publish: Optional[Dict[str, Any]] = None
    stable_publish: Optional[Dict[str, Any]] = None
    deploy: Optional[Dict[str, Any]] = None
    merge: Optional[Dict[str, Any]] = None
    rollback_command: str = ""
    blockers: List[str] = field(default_factory=list)
    verdict: str = "no_change_needed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id, "date": self.date, "branch": self.branch,
            "commit": self.commit,
            "learning_sources_checked": self.learning_sources_checked,
            "hf_datasets_scanned": self.hf_datasets_scanned,
            "web_searches_performed": self.web_searches_performed,
            "memories_written": self.memories_written,
            "improvement_targets": self.improvement_targets,
            "files_changed": self.files_changed,
            "tests": self.tests, "evals_before": self.evals_before,
            "evals_after": self.evals_after, "build": self.build, "gates": self.gates,
            "npm_version_before": self.npm_version_before,
            "npm_version_after": self.npm_version_after,
            "canary_publish": self.canary_publish, "stable_publish": self.stable_publish,
            "deploy": self.deploy, "merge": self.merge,
            "rollback_command": self.rollback_command, "blockers": self.blockers,
            "verdict": self.verdict,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def receipt_to_markdown(r: Dict[str, Any]) -> str:
    def yn(v):
        return "✅" if v else "❌"
    lines = [
        f"# Daily LOLM learned update — `{r['verdict']}`",
        "",
        f"- **run** `{r['run_id']}` · **date** {r['date']} · **branch** `{r.get('branch') or '—'}`",
        f"- **npm** {r.get('npm_version_before') or '—'} → {r.get('npm_version_after') or '—'}",
        f"- **files changed** {len(r.get('files_changed') or [])} · "
        f"**memories written** {r.get('memories_written', 0)} · "
        f"**HF datasets scanned** {r.get('hf_datasets_scanned', 0)}",
        "",
        "## Learning sources checked",
        "".join(f"\n- {s}" for s in (r.get("learning_sources_checked") or ["(none)"])),
        "",
        "## Improvement targets",
    ]
    for t in (r.get("improvement_targets") or []):
        lines.append(f"- `{t.get('kind')}` — {t.get('detail','')}")
    if not r.get("improvement_targets"):
        lines.append("- (none found — no_change_needed)")
    lines += ["", "## Gates"]
    g = r.get("gates") or {}
    for sub in ("merge", "publish", "deploy"):
        sg = g.get(sub)
        if isinstance(sg, dict):
            lines.append(f"- **{sub}** {yn(sg.get('passed'))}")
            for c in sg.get("checks", []):
                lines.append(f"  - {yn(c['passed'])} `{c['name']}` {c.get('detail','')}")
    lines += [
        "", "## Outcomes",
        f"- merge: {r.get('merge')}",
        f"- canary: {r.get('canary_publish')}",
        f"- stable: {r.get('stable_publish')}",
        f"- deploy: {r.get('deploy')}",
        "",
        "## Blockers",
    ]
    for b in (r.get("blockers") or []):
        lines.append(f"- ⛔ {b}")
    if not r.get("blockers"):
        lines.append("- (none)")
    lines += ["", f"**Rollback:** `{r.get('rollback_command') or '—'}`",
              "", f"**Verdict: `{r['verdict']}`**", ""]
    return "\n".join(lines)
