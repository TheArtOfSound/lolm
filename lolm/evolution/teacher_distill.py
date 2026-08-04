# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Distill verified teacher trajectories into student SFT/DPO data.

Hosted models remain teachers. When ensemble races produce a verified winner
and failed losers, we build:
  * SFT on the winning trajectory
  * Preference pairs (chosen=winner, rejected=losers)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lolm.evolution.schema import PreferencePair, default_paths, read_jsonl, write_jsonl


def distill_from_receipts(
    rows: Sequence[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Group by task; winners (ok/verified) vs losers → SFT + preference rows."""
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    paths = default_paths(repo_root)

    by_task: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        key = (r.get("task") or "").strip().lower()[:200]
        if not key:
            continue
        by_task.setdefault(key, []).append(r)

    sft: List[Dict[str, Any]] = []
    pairs: List[Dict[str, Any]] = []
    for task, group in by_task.items():
        wins = [g for g in group if g.get("independent_oracle") == "pass" or g.get("ok")]
        losses = [g for g in group if g.get("independent_oracle") == "fail" or g.get("ok") is False]
        if not wins:
            continue
        for w in wins:
            msgs = w.get("messages")
            if msgs:
                sft.append({
                    "messages": msgs,
                    "task_bucket": w.get("task_bucket") or "unknown",
                    "teacher": w.get("model") or w.get("winner") or "teacher",
                    "distill": True,
                    "trajectory_id": w.get("trajectory_id") or "",
                })
        if losses:
            for w in wins[:2]:
                chosen = _assistant(w)
                for l in losses[:3]:
                    rejected = _assistant(l)
                    if not chosen or not rejected or chosen == rejected:
                        continue
                    p = PreferencePair(
                        prompt=str(w.get("task") or task),
                        chosen=chosen,
                        rejected=rejected,
                        task_bucket=str(w.get("task_bucket") or "unknown"),
                        reason="teacher_win_vs_loss",
                        trajectory_id=str(w.get("trajectory_id") or ""),
                    )
                    pairs.append(p.to_dict())

    out_sft = paths.datasets / "teacher_sft.jsonl"
    out_pref = paths.datasets / "teacher_preference.jsonl"
    write_jsonl(out_sft, sft)
    write_jsonl(out_pref, pairs)
    # Merge into main preference file if pairs exist
    if pairs:
        existing = read_jsonl(paths.datasets / "preference_dpo.jsonl")
        seen = {e.get("pair_id") for e in existing}
        merged = existing + [p for p in pairs if p.get("pair_id") not in seen]
        write_jsonl(paths.datasets / "preference_dpo.jsonl", merged)

    return {
        "teacher_sft": len(sft),
        "teacher_pairs": len(pairs),
        "sft_path": str(out_sft),
        "pref_path": str(out_pref),
    }


def _assistant(row: Dict[str, Any]) -> str:
    for m in reversed(row.get("messages") or []):
        if str(m.get("role")).lower() == "assistant":
            return str(m.get("content") or "")
    return str((row.get("verification") or {}).get("verdict") or "")


def distill_from_gold(repo_root: Path) -> Dict[str, Any]:
    paths = default_paths(repo_root)
    gold = read_jsonl(paths.gold / "gold_latest.jsonl")
    silver = read_jsonl(paths.silver / "silver_latest.jsonl")
    return distill_from_receipts(gold + silver, repo_root=repo_root)
