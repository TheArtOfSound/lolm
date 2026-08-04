# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Controller-policy dataset: observed state → correct next control action.

Much stronger than predominantly synthetic controller scenarios when rows come
from real NFET trajectories and verified agent runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lolm.evolution.schema import (
    CONTROLLER_ACTIONS,
    ControllerExample,
    default_paths,
    read_jsonl,
    sha256_file,
    write_jsonl,
)

# Map free-form / legacy action names onto the canonical label set.
_ACTION_ALIASES = {
    "continue": "continue",
    "finalize": "finish",
    "finish": "finish",
    "done": "finish",
    "retrieve": "retrieve",
    "read": "read",
    "verify": "verify",
    "branch": "branch",
    "repair": "repair",
    "fix": "repair",
    "rollback": "rollback",
    "abstain": "abstain",
    "refuse": "abstain",
}


def normalize_action(action: str) -> str:
    a = (action or "continue").strip().lower()
    return _ACTION_ALIASES.get(a, a if a in CONTROLLER_ACTIONS else "continue")


def example_from_nfet_row(row: Dict[str, Any]) -> Optional[ControllerExample]:
    """From nfet_trajectories-style or harvest wrapper."""
    state = None
    action = None
    # harvested trajectory wrapper
    for a in row.get("actions_proposed") or []:
        if isinstance(a, dict) and "state" in a:
            state = a.get("state")
            action = a.get("type") or a.get("action")
            break
    if state is None and isinstance(row.get("state"), dict):
        state = row["state"]
        action = row.get("action")
    if not isinstance(state, dict) or not action:
        return None
    # Only use successful outcomes as positive labels when outcome present
    outcome = row.get("outcome") or (row.get("verification") or {}).get("outcome") or {}
    if outcome and outcome.get("exit_ok") is False:
        # still useful: map failure contexts to recovery actions if encoded
        pass
    return ControllerExample(
        state=dict(state),
        correct_action=normalize_action(str(action)),
        trajectory_id=str(row.get("trajectory_id") or row.get("run_id") or ""),
        source=str(row.get("source") or "nfet"),
    )


def examples_from_agent_trajectory(row: Dict[str, Any]) -> List[ControllerExample]:
    """Infer control labels from skillful agent trajectories."""
    out: List[ControllerExample] = []
    ver = row.get("verification") or {}
    files_read = row.get("files_read") or []
    mutations = row.get("mutations_applied") or []
    oracle = str(row.get("independent_oracle") or "")

    # Construct coarse state proxies
    base_state = {
        "tests_green": oracle == "pass",
        "files_modified": len(mutations),
        "files_read": len(files_read),
        "same_error_count": int(ver.get("attempts") or 1) - 1 if ver.get("attempts") else 0,
        "last_checkpoint_green": oracle == "pass",
        "trust_abort": bool(row.get("trust_abort")),
    }
    if files_read and not mutations:
        out.append(ControllerExample(state={**base_state, "phase": "inspect"}, correct_action="read",
                                     trajectory_id=str(row.get("trajectory_id") or ""), source="agent_infer"))
    if mutations and oracle == "pass":
        out.append(ControllerExample(state={**base_state, "phase": "verify"}, correct_action="verify",
                                     trajectory_id=str(row.get("trajectory_id") or ""), source="agent_infer"))
        out.append(ControllerExample(state={**base_state, "phase": "complete"}, correct_action="finish",
                                     trajectory_id=str(row.get("trajectory_id") or ""), source="agent_infer"))
    if oracle == "fail" and int(base_state["same_error_count"] or 0) >= 2:
        out.append(ControllerExample(
            state={**base_state, "tests_green": False},
            correct_action="rollback",
            trajectory_id=str(row.get("trajectory_id") or ""),
            source="agent_infer",
        ))
    if row.get("trust_abort"):
        out.append(ControllerExample(
            state={**base_state, "trust_abort": True},
            correct_action="abstain",
            trajectory_id=str(row.get("trajectory_id") or ""),
            source="agent_infer",
        ))
    return out


def build_controller_dataset(
    rows: Sequence[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
    out_name: str = "controller_policy.jsonl",
) -> Dict[str, Any]:
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    paths = default_paths(repo_root)
    examples: List[ControllerExample] = []
    for r in rows:
        ex = example_from_nfet_row(r)
        if ex:
            examples.append(ex)
        examples.extend(examples_from_agent_trajectory(r))

    # keep only canonical actions
    cleaned = [e.to_dict() for e in examples if e.correct_action in CONTROLLER_ACTIONS]
    out = paths.datasets / out_name
    write_jsonl(out, cleaned)
    counts: Dict[str, int] = {}
    for e in cleaned:
        a = e["correct_action"]
        counts[a] = counts.get(a, 0) + 1
    return {
        "path": str(out),
        "count": len(cleaned),
        "action_counts": counts,
        "dataset_sha256": sha256_file(out) if out.exists() else "",
    }


def build_controller_from_repo(repo_root: Path) -> Dict[str, Any]:
    paths = default_paths(repo_root)
    gold = read_jsonl(paths.gold / "gold_latest.jsonl")
    # also raw nfet if gold is sparse
    nfet = read_jsonl(Path(repo_root) / "runs" / "nfet_trajectories.jsonl")
    return build_controller_dataset(gold + nfet, repo_root=repo_root)
