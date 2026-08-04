# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Build DPO / preference pairs from verified successes vs failures.

Examples of chosen vs rejected:
  * correct file vs misleading same-named file
  * read-first vs blind rewrite
  * verified DONE vs premature DONE
  * rollback vs continued mutation after regression
  * supported factual answer vs unsupported claim
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lolm.evolution.schema import (
    PreferencePair,
    default_paths,
    read_jsonl,
    sha256_file,
    write_jsonl,
)


def _assistant_text(row: Dict[str, Any]) -> str:
    msgs = row.get("messages") or []
    for m in reversed(msgs):
        if str(m.get("role") or "").lower() == "assistant":
            return str(m.get("content") or "")
    ver = row.get("verification") or {}
    return str(ver.get("verdict") or row.get("independent_oracle") or "")


def _user_text(row: Dict[str, Any]) -> str:
    msgs = row.get("messages") or []
    for m in msgs:
        if str(m.get("role") or "").lower() == "user":
            return str(m.get("content") or "")
    return str(row.get("task") or "")


# Synthetic skill contrasts when we lack paired trajectories for the same task.
SKILL_PAIRS: List[Tuple[str, str, str, str]] = [
    (
        "Fix the parser regression in this repository.",
        "READ: parser.py\nEDIT: parser.py (minimal fix)\nRUN: pytest\ntests passed\nDONE: verified",
        "EDIT: parser.py\nDONE: fixed",
        "read_before_edit",
    ),
    (
        "Tests failed after your last edit. What do you do?",
        "ROLLBACK to last green checkpoint, re-read failing tests, replan a minimal repair.",
        "Continue editing more files until something works.",
        "rollback",
    ),
    (
        "Complete the task when evidence is insufficient.",
        "ABSTAIN: evidence incomplete; cannot ship.",
        "DONE: verified",
        "abstain",
    ),
    (
        "Two files named utils.py exist. Which do you edit?",
        "READ both paths; select the package utils that imports the failing symbol; edit that one.",
        "EDIT: utils.py in the first directory I see.",
        "file_selection",
    ),
    (
        "Claim the API is fixed without running tests.",
        "I will not claim completion. RUN tests and attach verifier output first.",
        "DONE: API fixed.",
        "avoid_false_completion",
    ),
]


def pairs_from_same_task(rows: Sequence[Dict[str, Any]]) -> List[PreferencePair]:
    """Group by normalized task; success = chosen, failure = rejected."""
    by_task: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = (r.get("task") or _user_text(r) or "").strip().lower()[:200]
        if key:
            by_task[key].append(r)

    pairs: List[PreferencePair] = []
    for task, group in by_task.items():
        wins = [g for g in group if str(g.get("independent_oracle")) == "pass"]
        losses = [g for g in group if str(g.get("independent_oracle")) == "fail"]
        if not wins or not losses:
            continue
        for w in wins[:3]:
            for l in losses[:3]:
                pairs.append(PreferencePair(
                    prompt=_user_text(w) or task,
                    chosen=_assistant_text(w) or "DONE: verified",
                    rejected=_assistant_text(l) or "DONE: fixed",
                    task_bucket=str(w.get("task_bucket") or "unknown"),
                    reason="oracle_pass_vs_fail",
                    trajectory_id=str(w.get("trajectory_id") or ""),
                ))
    return pairs


def pairs_from_actions(rows: Sequence[Dict[str, Any]]) -> List[PreferencePair]:
    """actions_proposed vs actions_rejected on the same trajectory."""
    pairs: List[PreferencePair] = []
    for r in rows:
        proposed = r.get("actions_proposed") or []
        rejected = r.get("actions_rejected") or []
        if not proposed or not rejected:
            continue
        prompt = _user_text(r) or str(r.get("task") or "")
        for a in proposed[:2]:
            for b in rejected[:2]:
                pairs.append(PreferencePair(
                    prompt=prompt,
                    chosen=str(a if not isinstance(a, dict) else a.get("type") or a),
                    rejected=str(b if not isinstance(b, dict) else b.get("type") or b),
                    task_bucket=str(r.get("task_bucket") or "unknown"),
                    reason="proposed_vs_rejected_action",
                    trajectory_id=str(r.get("trajectory_id") or ""),
                ))
    return pairs


def skill_seed_pairs() -> List[PreferencePair]:
    return [
        PreferencePair(prompt=p, chosen=c, rejected=r, task_bucket="skill", reason=reason)
        for p, c, r, reason in SKILL_PAIRS
    ]


def build_preference_dataset(
    gold_and_silver: Sequence[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
    include_skill_seeds: bool = True,
    out_name: str = "preference_dpo.jsonl",
) -> Dict[str, Any]:
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    paths = default_paths(repo_root)
    pairs = pairs_from_same_task(gold_and_silver) + pairs_from_actions(gold_and_silver)
    if include_skill_seeds:
        pairs.extend(skill_seed_pairs())

    # Dedupe by pair_id
    seen = set()
    uniq: List[PreferencePair] = []
    for p in pairs:
        d = p.to_dict()
        if d["pair_id"] in seen:
            continue
        seen.add(d["pair_id"])
        uniq.append(p)

    trl_rows = [p.to_trl_row() for p in uniq]
    # Also emit simple chosen/rejected for mlx or custom trainers
    simple = [p.to_dict() for p in uniq]

    out = paths.datasets / out_name
    trl_out = paths.datasets / out_name.replace(".jsonl", "_trl.jsonl")
    write_jsonl(out, simple)
    write_jsonl(trl_out, trl_rows)

    return {
        "path": str(out),
        "trl_path": str(trl_out),
        "pair_count": len(uniq),
        "dataset_sha256": sha256_file(out) if out.exists() else "",
    }


def build_preference_from_files(repo_root: Path) -> Dict[str, Any]:
    paths = default_paths(repo_root)
    gold = read_jsonl(paths.gold / "gold_latest.jsonl")
    silver = read_jsonl(paths.silver / "silver_latest.jsonl")
    # failures live in silver/bronze often
    return build_preference_dataset(gold + silver, repo_root=repo_root)
