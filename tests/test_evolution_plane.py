# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Evolution plane — first milestone: receipts → gold → sft/dpo → eval → promote."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lolm.evolution.contamination import is_contaminated
from lolm.evolution.cycle import run_evolution_cycle, thresholds_met
from lolm.evolution.deduplicate import deduplicate
from lolm.evolution.evaluate_candidate import (
    gate_frozen_suite,
    gate_weight_integrity,
)
from lolm.evolution.gold_filter import evaluate_gold, silver_to_gold
from lolm.evolution.harvest import harvest_repo, trajectory_from_code_receipt
from lolm.evolution.preference_builder import build_preference_dataset, skill_seed_pairs
from lolm.evolution.privacy import clear_trajectory, scan_pii
from lolm.evolution.promote import promote_candidate
from lolm.evolution.rollback import rollback_to_previous
from lolm.evolution.schema import Trajectory, default_paths
from lolm.evolution.sft_builder import build_sft_dataset, trajectory_to_sft
from lolm.evolution.shadow_compare import shadow_compare
from lolm.evolution.train_candidate import train_candidate


def _seed_receipts(repo: Path) -> None:
    runs = repo / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    code = [
        {
            "kind": "visual_build",
            "task": "build a maze game",
            "verified": True,
            "verifier_ran": True,
            "attempts": 2,
            "winner": "local/qwen-3b",
            "ok": True,
            "verdict": "verified",
            "html_sha": "abc123",
            "receipt_sha": "rec1",
            "ledger_sha": "led1",
            "reasons": [],
        },
        {
            "kind": "visual_build",
            "task": "build a maze game",
            "verified": False,
            "ok": False,
            "verdict": "failed",
            "winner": "cloud",
            "reasons": ["frozen"],
            "receipt_sha": "rec2",
            "attempts": 4,
        },
        {
            "kind": "code",
            "task": "Fix the parser regression",
            "verified": True,
            "ok": True,
            "verdict": "verified",
            "winner": "local/qwen-3b",
            "receipt_sha": "rec3",
            "ledger_sha": "led3",
            "attempts": 1,
        },
    ]
    (runs / "code_receipts.jsonl").write_text(
        "\n".join(json.dumps(r) for r in code) + "\n"
    )
    nfet = [
        {
            "ts": 1,
            "run_id": "r1",
            "state": {"uncertainty": 0.8, "verification_need": 1.0},
            "action": "retrieve",
            "consumed": True,
            "outcome": {"exit_ok": True},
        },
        {
            "ts": 2,
            "state": {"uncertainty": 0.2},
            "action": "finalize",
            "consumed": True,
            "outcome": {"exit_ok": True},
        },
    ]
    (runs / "nfet_trajectories.jsonl").write_text(
        "\n".join(json.dumps(r) for r in nfet) + "\n"
    )


def test_trajectory_schema_and_privacy():
    t = Trajectory(
        task="Fix parser",
        model="local/qwen",
        messages=[
            {"role": "user", "content": "fix it"},
            {"role": "assistant", "content": "READ: parser.py"},
        ],
        independent_oracle="pass",
        receipt_signature_valid=True,
        privacy_cleared=True,
    )
    t.compute_id()
    assert len(t.trajectory_id) == 24
    d, report = clear_trajectory({
        **t.to_dict(),
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
        "note": "contact me@example.com",
    })
    assert d["api_key"] == "***REDACTED***"
    assert "email" in scan_pii("x@y.com") or scan_pii("x@y.com")


def test_gold_filter_rejects_weak_rows():
    ok, reasons = evaluate_gold({
        "receipt_signature_valid": False,
        "independent_oracle": "fail",
        "privacy_cleared": False,
        "model": "unknown",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert not ok
    assert "oracle=fail" in reasons

    good = {
        "receipt_signature_valid": True,
        "independent_oracle": "pass",
        "privacy_cleared": True,
        "model": "local/qwen",
        "messages": [
            {"role": "user", "content": "fix"},
            {"role": "assistant", "content": "READ then EDIT"},
        ],
        "skill_tags": ["read_before_edit"],
        "training_permitted": True,
        "benchmark_contaminated": False,
    }
    ok2, reasons2 = evaluate_gold(good)
    assert ok2, reasons2


def test_contamination_and_dedup():
    assert is_contaminated("Write a HumanEval solution for sorting")
    rows = [
        {"task": "a", "messages": [1], "content_sha256": "x"},
        {"task": "a", "messages": [1], "content_sha256": "x"},
        {"task": "b", "messages": [2], "content_sha256": "y"},
    ]
    kept, stats = deduplicate(rows)
    assert stats["kept"] == 2
    assert stats["dropped"] == 1


def test_harvest_sft_preference_cycle(tmp_path: Path):
    _seed_receipts(tmp_path)
    h = harvest_repo(tmp_path)
    assert h["count"] >= 3
    bronze = Path(h["bronze_path"])
    assert bronze.exists()

    from lolm.evolution.gold_filter import build_gold_pipeline
    g = build_gold_pipeline(tmp_path, bronze_path=bronze)
    assert g["gold_count"] >= 1

    gold_rows = [
        json.loads(line)
        for line in Path(g["gold_path"]).read_text().splitlines()
        if line.strip()
    ]
    sft = build_sft_dataset(gold_rows, repo_root=tmp_path, use_replay=True, target_size=20, seed=1)
    assert sft["train_count"] >= 10
    assert Path(sft["train_path"]).exists()

    pref = build_preference_dataset(gold_rows, repo_root=tmp_path)
    assert pref["pair_count"] >= len(skill_seed_pairs())


def test_train_eval_promote_rollback(tmp_path: Path):
    _seed_receipts(tmp_path)
    harvest_repo(tmp_path)
    from lolm.evolution.gold_filter import build_gold_pipeline
    build_gold_pipeline(tmp_path)
    gold = default_paths(tmp_path).gold / "gold_latest.jsonl"
    rows = [json.loads(l) for l in gold.read_text().splitlines() if l.strip()]
    build_sft_dataset(rows, repo_root=tmp_path, target_size=16)

    train = train_candidate(tmp_path, dry_run=True)
    cand = Path(train["candidate_dir"])
    assert (cand / "adapters.safetensors").exists()

    g1 = gate_weight_integrity(cand)
    assert g1.passed
    g2 = gate_frozen_suite()  # heuristic probe
    assert g2.passed

    shadow = shadow_compare(tmp_path)
    assert shadow["shadow_wins"] >= shadow["shadow_losses"]

    from lolm.evolution.evaluate_candidate import evaluate_candidate
    ev = evaluate_candidate(tmp_path, cand, require_shadow=True, shadow_result=shadow)
    assert ev["offline_ok"]

    # first promote becomes live
    p1 = promote_candidate(tmp_path, cand, ev, canary_pct=0.05)
    assert p1["decision"] in ("canary", "promoted")
    live = default_paths(tmp_path).live / "adapter"
    assert live.exists()

    # second candidate to create previous_known_good
    train2 = train_candidate(tmp_path, dry_run=True)
    cand2 = Path(train2["candidate_dir"])
    ev2 = evaluate_candidate(tmp_path, cand2, require_shadow=True, shadow_result=shadow)
    promote_candidate(tmp_path, cand2, ev2, canary_pct=0.05)

    rb = rollback_to_previous(tmp_path, reason="test")
    assert rb["decision"] == "rolled_back"


def test_full_cycle_force_dry(tmp_path: Path):
    _seed_receipts(tmp_path)
    report = run_evolution_cycle(
        tmp_path,
        dry_run=True,
        force=True,
        canary_pct=0.05,
        require_shadow=True,
    )
    assert report["decision"] in (
        "canary", "promoted", "rejected", "candidate_dry_run",
        "deferred_insufficient_data",
    )
    assert "harvest" in report["steps"]
    assert "sft" in report["steps"]
    # force path always trains
    assert "train" in report["steps"]
    assert report["steps"]["train"].get("dry_run") is True


def test_trajectory_dual_write_from_code_receipt(tmp_path: Path):
    from lolm.evolution.trajectory_log import dual_write_receipt, receipt_to_trajectory
    row = {
        "kind": "code_agent",
        "task": "Fix the parser regression",
        "ok": True,
        "verdict": "shipped",
        "winner": "teacher/gpt",
        "receipt_sha": "abc",
        "trail": [
            {"op": "read", "path": "parser.py", "bytes": 10},
            {"op": "edit", "path": "parser.py", "ok": True},
            {"op": "run", "command": "pytest", "exit": 0, "stdout_tail": "passed"},
        ],
        "files": ["parser.py"],
        "green_runs": 1,
        "failed_runs": 0,
        "verifies": 1,
    }
    t = receipt_to_trajectory(row)
    assert any(m.get("content", "").startswith("READ:") for m in t.messages)
    assert t.independent_oracle == "pass"
    out = dual_write_receipt(row, repo_root=tmp_path)
    assert out and out.get("trajectory_id")
    stream = tmp_path / "runs" / "evolution" / "raw" / "bronze_stream.jsonl"
    assert stream.exists()


def test_canary_select(tmp_path: Path):
    from lolm.evolution.canary import select_adapter, advance_canary
    from lolm.evolution.schema import default_paths
    paths = default_paths(tmp_path)
    live = paths.live / "adapter"
    live.mkdir(parents=True)
    (live / "adapters.safetensors").write_bytes(b"x" * 100)
    (paths.live / "manifest.json").write_text(json.dumps({
        "canary_pct": 0.05, "decision": "canary", "model_version": "v1",
    }))
    path, meta = select_adapter(tmp_path, request_id="req-1")
    assert meta.get("canary_pct") == 0.05
    adv = advance_canary(tmp_path, eval_ok=True, shadow_win_rate=0.8)
    assert adv.get("advanced") is True
    assert adv.get("canary_pct") == 0.25


def test_thresholds_not_met_on_empty(tmp_path: Path):
    default_paths(tmp_path)
    thr = thresholds_met(tmp_path)
    assert thr["met"] is False
