# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Deduplicate trajectories by content hash and near-duplicate task text."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from lolm.evolution.schema import Trajectory


def _norm_task(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s./-]", "", t)
    return t[:400]


def content_key(traj: Trajectory | Dict[str, Any]) -> str:
    if isinstance(traj, Trajectory):
        if traj.content_sha256:
            return traj.content_sha256
        traj.compute_id()
        return traj.content_sha256
    d = traj
    if d.get("content_sha256"):
        return str(d["content_sha256"])
    body = {
        "task": d.get("task"),
        "messages": d.get("messages"),
        "mutations_applied": d.get("mutations_applied"),
        "final_tree_hash": d.get("final_tree_hash"),
        "model": d.get("model"),
        "run_id": d.get("run_id"),
    }
    import json
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def deduplicate(
    rows: Sequence[Trajectory | Dict[str, Any]],
    *,
    by_task_norm: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Keep first occurrence of each content hash (and optionally normalized task)."""
    seen_hash: Set[str] = set()
    seen_task: Set[str] = set()
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for item in rows:
        d = item.to_dict() if isinstance(item, Trajectory) else dict(item)
        h = content_key(d)
        if h in seen_hash:
            dropped += 1
            continue
        if by_task_norm:
            tn = _norm_task(str(d.get("task") or ""))
            # allow controller steps with same action text via hash only
            if tn and d.get("task_bucket") != "controller" and tn in seen_task:
                dropped += 1
                continue
            if tn:
                seen_task.add(tn)
        seen_hash.add(h)
        d["content_sha256"] = h
        kept.append(d)
    return kept, {"input": len(rows), "kept": len(kept), "dropped": dropped}
