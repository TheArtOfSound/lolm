# Copyright (c) 2026 Qira LLC. All rights reserved.
"""One full evolution cycle (data-threshold gated).

  1. Harvest receipts (+ bronze stream dual-writes)
  2. Redact / validate → Silver → Gold
  3. Teacher distill + SFT + DPO-as-SFT + controller + verifier
  4. Train candidate adapter (real MLX when available)
  5. Frozen + real-task eval
  6. Shadow compare
  7. Promote (canary) or reject
  8. Optionally advance canary stage
  9. Sign model receipt / registry
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from lolm.evolution.canary import advance_canary
from lolm.evolution.controller_builder import build_controller_from_repo
from lolm.evolution.dpo_train import merge_sft_with_preferences, try_trl_dpo
from lolm.evolution.evaluate_candidate import evaluate_candidate
from lolm.evolution.gold_filter import build_gold_pipeline
from lolm.evolution.harvest import harvest_repo
from lolm.evolution.preference_builder import build_preference_from_files
from lolm.evolution.promote import promote_candidate, reject_candidate
from lolm.evolution.schema import DataThresholds, default_paths, read_jsonl
from lolm.evolution.sft_builder import build_sft_from_gold_file
from lolm.evolution.shadow_compare import shadow_compare
from lolm.evolution.teacher_distill import distill_from_gold
from lolm.evolution.train_candidate import train_candidate
from lolm.evolution.verifier_builder import build_verifier_from_repo

# Bootstrap: allow training earlier than production 500-Gold once skills exist.
BOOTSTRAP = DataThresholds(
    min_gold_trajectories=8,
    min_preference_pairs=5,
    min_per_bucket=1,
)


def thresholds_met(
    repo_root: Path,
    thr: Optional[DataThresholds] = None,
    *,
    force: bool = False,
    bootstrap: bool = True,
) -> Dict[str, Any]:
    thr = thr or (BOOTSTRAP if bootstrap else DataThresholds())
    if force:
        return {"met": True, "forced": True, "mode": "force"}
    paths = default_paths(repo_root)
    gold = read_jsonl(paths.gold / "gold_latest.jsonl")
    prefs = read_jsonl(paths.datasets / "preference_dpo.jsonl")
    buckets: Dict[str, int] = {}
    for g in gold:
        b = str(g.get("task_bucket") or "unknown")
        buckets[b] = buckets.get(b, 0) + 1
    skill_gold = [g for g in gold if g.get("task_bucket") != "controller"]
    low_buckets = {
        k: v for k, v in buckets.items()
        if k not in ("controller",) and v < thr.min_per_bucket
    }
    checks = {
        "gold_trajectories": len(gold) >= thr.min_gold_trajectories
        or len(skill_gold) >= thr.min_gold_trajectories,
        "preference_pairs": len(prefs) >= thr.min_preference_pairs,
        "per_bucket": True,
    }
    if len(gold) >= thr.min_gold_trajectories:
        checks["per_bucket"] = len(low_buckets) == 0
    met = all(checks.values())
    return {
        "met": met,
        "checks": checks,
        "gold_count": len(gold),
        "skill_gold": len(skill_gold),
        "pref_count": len(prefs),
        "buckets": buckets,
        "low_buckets": low_buckets,
        "thresholds": {
            "min_gold": thr.min_gold_trajectories,
            "min_prefs": thr.min_preference_pairs,
            "min_per_bucket": thr.min_per_bucket,
        },
        "mode": "bootstrap" if bootstrap and thr.min_gold_trajectories < 500 else "production",
    }


def _mlx_available() -> bool:
    try:
        import mlx_lm  # noqa: F401
        return True
    except ImportError:
        return False


def run_evolution_cycle(
    repo_root: Path,
    *,
    dry_run: Optional[bool] = None,
    force: bool = False,
    canary_pct: float = 0.05,
    require_shadow: bool = True,
    skip_train: bool = False,
    thr: Optional[DataThresholds] = None,
    advance_canary_stage: bool = True,
    try_dpo: bool = True,
) -> Dict[str, Any]:
    """Execute the product evolution loop."""
    repo_root = Path(repo_root)
    paths = default_paths(repo_root)
    t0 = time.time()
    report: Dict[str, Any] = {"ts": int(t0), "steps": {}}

    if dry_run is None:
        dry_run = os.environ.get("LOLM_EVOLUTION_DRY_RUN") == "1" or not _mlx_available()

    # 1–2 harvest + gold
    report["steps"]["harvest"] = harvest_repo(repo_root)
    report["steps"]["gold"] = build_gold_pipeline(repo_root)

    # 3 datasets
    report["steps"]["sft"] = build_sft_from_gold_file(repo_root)
    report["steps"]["preference"] = build_preference_from_files(repo_root)
    report["steps"]["teacher"] = distill_from_gold(repo_root)
    report["steps"]["preference_sft"] = merge_sft_with_preferences(repo_root)
    report["steps"]["controller"] = build_controller_from_repo(repo_root)
    report["steps"]["verifier"] = build_verifier_from_repo(repo_root)

    gate = thresholds_met(repo_root, thr, force=force, bootstrap=True)
    report["data_threshold"] = gate
    if not gate["met"] and not force:
        report["decision"] = "deferred_insufficient_data"
        report["seconds"] = round(time.time() - t0, 2)
        (paths.receipts / "cycle_latest.json").write_text(json.dumps(report, indent=2, default=str))
        return report

    if skip_train:
        report["decision"] = "datasets_ready"
        report["seconds"] = round(time.time() - t0, 2)
        (paths.receipts / "cycle_latest.json").write_text(json.dumps(report, indent=2, default=str))
        return report

    # Optional full TRL DPO (usually skipped on Mac)
    if try_dpo and not dry_run:
        dpo_out = paths.candidates / f"dpo_{int(time.time())}"
        report["steps"]["trl_dpo"] = try_trl_dpo(
            repo_root,
            model_name=os.environ.get("LOLM_DPO_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
            output_dir=dpo_out,
        )

    # 4 train (multi-role: agent-policy primary)
    primary_iters = 40 if dry_run else 120
    train = train_candidate(
        repo_root, dry_run=bool(dry_run), resume_from_live=True, iters=primary_iters,
    )
    report["steps"]["train"] = {k: v for k, v in train.items() if k != "manifest"}
    report["steps"]["train"]["dry_run"] = bool(dry_run)
    cand = Path(train["candidate_dir"])

    # Multi-role secondary adapters — lighter iters; skip real train if primary was dry
    for role in ("lolm-code-repair", "lolm-verifier"):
        try:
            rtrain = train_candidate(
                repo_root,
                dry_run=bool(dry_run),
                role=role,
                resume_from_live=False,
                iters=20 if dry_run else 60,
            )
            report["steps"][f"train_{role}"] = {
                "model_version": rtrain.get("model_version"),
                "candidate_dir": rtrain.get("candidate_dir"),
                "dry_run": bool(dry_run),
            }
        except Exception as exc:
            report["steps"][f"train_{role}"] = {"error": str(exc)[:200]}

    # 6 shadow before full eval
    shadow = shadow_compare(repo_root)
    report["steps"]["shadow"] = shadow

    # 5 eval
    ev = evaluate_candidate(
        repo_root,
        cand,
        require_shadow=require_shadow,
        shadow_result=shadow,
    )
    report["steps"]["evaluate"] = ev

    # 7 promote / reject
    if ev.get("promote_ready") or (ev.get("offline_ok") and canary_pct < 1.0):
        # Never full-promote dry-run stubs into "served" as real weights
        effective_canary = 0.0 if dry_run else canary_pct
        if dry_run:
            report["steps"]["promote"] = promote_candidate(
                repo_root, cand, ev, canary_pct=0.0, force=True,
            )
            # Mark dry-run so serve skips it
            man_path = paths.live / "manifest.json"
            if man_path.exists():
                man = json.loads(man_path.read_text())
                man["dry_run"] = True
                man["canary_pct"] = 0.0
                man["decision"] = "candidate_dry_run"
                man_path.write_text(json.dumps(man, indent=2))
            report["decision"] = "candidate_dry_run"
        else:
            report["steps"]["promote"] = promote_candidate(
                repo_root, cand, ev, canary_pct=effective_canary,
            )
            report["decision"] = report["steps"]["promote"].get("decision")
            if advance_canary_stage and report["decision"] in ("canary", "promoted"):
                report["steps"]["canary_advance"] = advance_canary(
                    repo_root,
                    eval_ok=bool(ev.get("offline_ok")),
                    shadow_win_rate=float(shadow.get("win_rate") or 0.0),
                )
    else:
        report["steps"]["promote"] = reject_candidate(repo_root, cand, ev)
        report["decision"] = "rejected"

    report["seconds"] = round(time.time() - t0, 2)
    (paths.receipts / "cycle_latest.json").write_text(json.dumps(report, indent=2, default=str))
    return report
