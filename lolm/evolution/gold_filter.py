# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Promote Bronze/Silver trajectories to Gold when train-safe.

A trajectory enters Gold only when:
  * receipt signature is valid (or trusted local control log);
  * independent oracle passes;
  * no trust violation;
  * secrets/PII cleared;
  * model identity known;
  * not benchmark-contaminated;
  * training permitted;
  * not a pure volatile-fact dump (skills/policies only for weights).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lolm.evolution.contamination import mark_contamination
from lolm.evolution.deduplicate import deduplicate
from lolm.evolution.schema import (
    VOLATILE_FACT_TAGS,
    GoldCriteria,
    Trajectory,
    TrajectoryTier,
    default_paths,
    read_jsonl,
    write_jsonl,
)


def _is_volatile_only(row: Dict[str, Any]) -> bool:
    tags = set(row.get("volatile_tags") or [])
    skills = set(row.get("skill_tags") or [])
    if tags & VOLATILE_FACT_TAGS and not skills:
        return True
    # Heuristic: pricing/quota curriculum style Q/A without tool trajectory
    task = str(row.get("task") or "").lower()
    vol_kw = ("priced at", "costs $", "quota", "per month", "daily run limit", "https://")
    if any(k in task for k in vol_kw) and len(row.get("messages") or []) <= 2:
        if not (row.get("files_read") or row.get("mutations_applied") or row.get("commands_run")):
            return True
    return False


def evaluate_gold(
    row: Dict[str, Any],
    criteria: Optional[GoldCriteria] = None,
) -> tuple[bool, List[str]]:
    c = criteria or GoldCriteria()
    reasons: List[str] = []

    if c.require_receipt_signature and not row.get("receipt_signature_valid"):
        # Local nfet control logs are allowed via source override
        if row.get("source") != "nfet_trajectories":
            reasons.append("receipt_signature_invalid")

    if c.require_oracle_pass and str(row.get("independent_oracle") or "") != "pass":
        reasons.append(f"oracle={row.get('independent_oracle')}")

    if c.require_no_trust_abort and row.get("trust_abort"):
        reasons.append("trust_abort")

    if c.require_privacy_cleared and not row.get("privacy_cleared"):
        reasons.append("privacy_not_cleared")

    if c.require_model_known:
        model = str(row.get("model") or "").strip().lower()
        if not model or model in ("unknown", "none", "?"):
            reasons.append("model_unknown")

    if c.require_no_contamination and row.get("benchmark_contaminated"):
        reasons.append("benchmark_contaminated")

    if c.require_training_permitted and row.get("training_permitted") is False:
        reasons.append("training_not_permitted")

    if c.require_no_volatile_only and _is_volatile_only(row):
        reasons.append("volatile_facts_only")

    msgs = row.get("messages") or []
    if len(msgs) < c.min_messages:
        reasons.append("too_few_messages")

    return (not reasons), reasons


def bronze_to_silver(
    bronze_rows: Sequence[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Structural validity + dedupe + contamination mark → Silver."""
    # Structural: must have task or messages
    structural: List[Dict[str, Any]] = []
    bad_struct = 0
    for r in bronze_rows:
        if not (r.get("task") or r.get("messages")):
            bad_struct += 1
            continue
        r = dict(r)
        r["tier"] = TrajectoryTier.SILVER.value
        structural.append(r)

    deduped, dedup_stats = deduplicate(structural)
    marked, contam_stats = mark_contamination(deduped, repo_root=repo_root)
    stats = {
        "input": len(bronze_rows),
        "structural_drop": bad_struct,
        "dedup": dedup_stats,
        "contamination": contam_stats,
        "silver": len(marked),
    }
    return marked, stats


def silver_to_gold(
    silver_rows: Sequence[Dict[str, Any]],
    criteria: Optional[GoldCriteria] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    c = criteria or GoldCriteria()
    gold: List[Dict[str, Any]] = []
    rejects: Dict[str, int] = {}
    for r in silver_rows:
        ok, reasons = evaluate_gold(r, c)
        if ok:
            r = dict(r)
            r["tier"] = TrajectoryTier.GOLD.value
            gold.append(r)
        else:
            for reason in reasons:
                rejects[reason] = rejects.get(reason, 0) + 1
    return gold, {"input": len(silver_rows), "gold": len(gold), "reject_reasons": rejects}


def build_gold_pipeline(
    repo_root: Path,
    *,
    bronze_path: Optional[Path] = None,
    criteria: Optional[GoldCriteria] = None,
) -> Dict[str, Any]:
    """Bronze latest → Silver → Gold files under runs/evolution/."""
    repo_root = Path(repo_root)
    paths = default_paths(repo_root)
    bronze_path = Path(bronze_path) if bronze_path else paths.raw / "bronze_latest.jsonl"
    bronze = read_jsonl(bronze_path)

    silver, silver_stats = bronze_to_silver(bronze, repo_root=repo_root)
    gold, gold_stats = silver_to_gold(silver, criteria=criteria)

    silver_out = paths.silver / "silver_latest.jsonl"
    gold_out = paths.gold / "gold_latest.jsonl"
    write_jsonl(silver_out, silver)
    write_jsonl(gold_out, gold)

    return {
        "bronze_path": str(bronze_path),
        "silver_path": str(silver_out),
        "gold_path": str(gold_out),
        "silver_stats": silver_stats,
        "gold_stats": gold_stats,
        "gold_count": len(gold),
    }
