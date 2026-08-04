# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Harvest product receipts into Bronze trajectories.

Sources (existing LOLM artifacts under runs/):
  * code_receipts.jsonl — visual/code builds with independent verifier verdicts
  * claude_receipts.jsonl — agent receipts
  * nfet_trajectories.jsonl — controller (state → action) steps
  * autonomy_flywheel.jsonl — calibrated correctness pairs (meta only)

Volatile product facts (pricing, quotas, URLs) are tagged but not treated as
skill training material.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from lolm.evolution.privacy import clear_trajectory
from lolm.evolution.schema import (
    Trajectory,
    TrajectoryTier,
    append_jsonl,
    default_paths,
    read_jsonl,
    write_jsonl,
)

# Heuristics: classify task buckets from free text.
_BUCKET_RULES: Sequence[tuple[str, re.Pattern[str]]] = (
    ("multi_file_repair", re.compile(r"multi[- ]?file|refactor|across files", re.I)),
    ("code_repair", re.compile(r"fix|bug|repair|patch|regression", re.I)),
    ("frontend", re.compile(r"html|css|react|frontend|ui|maze|game", re.I)),
    ("api", re.compile(r"\bapi\b|endpoint|http|webhook", re.I)),
    ("config", re.compile(r"config|yaml|toml|env|setting", re.I)),
    ("grounded_qa", re.compile(r"what is|who|when|price|quota|document", re.I)),
    ("command", re.compile(r"run |command|shell|cli", re.I)),
    ("tool_use", re.compile(r"tool|read:|edit:|retrieve", re.I)),
)


def infer_bucket(task: str, kind: str = "") -> str:
    text = f"{kind} {task}".strip()
    for name, pat in _BUCKET_RULES:
        if pat.search(text):
            return name
    return "unknown"


def _skill_tags_from_receipt(row: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    if row.get("verified") or row.get("verdict") in ("verified", "pass", "ok"):
        tags.append("verify_work")
    reasons = row.get("reasons") or []
    if any("read" in str(r).lower() for r in reasons):
        tags.append("read_before_edit")
    if row.get("kind") in ("visual_build", "code"):
        tags.extend(["tool_use", "repo_inspect"])
    if row.get("ok") is False or row.get("verified") is False:
        tags.append("patch_recovery")
    return sorted(set(tags))


def trajectory_from_code_receipt(row: Dict[str, Any], source_path: str = "") -> Trajectory:
    # Prefer full trail expansion when present (code agent receipts).
    if row.get("trail") or row.get("files") or row.get("kind") == "code_agent":
        try:
            from lolm.evolution.trajectory_log import receipt_to_trajectory
            t = receipt_to_trajectory(row, source="code_receipts")
            t.source_path = source_path
            return t
        except Exception:
            pass
    task = str(row.get("task") or row.get("prompt") or "")
    verified = bool(
        row.get("verified") or row.get("ok")
        or row.get("verdict") in ("verified", "shipped")
    )
    oracle = "pass" if verified else ("fail" if row.get("verified") is False or row.get("ok") is False else "unknown")
    model = str(row.get("winner") or row.get("model") or "code_agent")
    provider = str(row.get("provider") or row.get("source") or "")
    assistant_bits = []
    if row.get("verdict"):
        assistant_bits.append(f"DONE: {row.get('verdict')}" if verified else f"INCOMPLETE: {row.get('verdict')}")
    if row.get("reasons"):
        assistant_bits.append("reasons: " + ", ".join(map(str, row["reasons"])))
    messages = [
        {"role": "user", "content": task or "(no task text)"},
        {"role": "assistant", "content": "\n".join(assistant_bits) or "(no assistant text)"},
    ]
    # Prefer receipt_sha presence as soft signature evidence when ledger_sha present.
    sig_ok = bool(row.get("receipt_sha") or row.get("ledger_sha") or row.get("receipt_signature_valid")
                  or row.get("signature") or row.get("receipt_signature"))
    t = Trajectory(
        task=task,
        task_bucket=infer_bucket(task, str(row.get("kind") or "")),
        model=model if model else "code_agent",
        provider=provider,
        messages=messages,
        verification={
            "verdict": row.get("verdict"),
            "verified": row.get("verified"),
            "ok": row.get("ok"),
            "reasons": row.get("reasons") or [],
            "verifier_ran": row.get("verifier_ran"),
            "attempts": row.get("attempts"),
        },
        final_tree_hash=str(row.get("html_sha") or row.get("final_tree_hash") or row.get("tree_hash") or ""),
        independent_oracle=oracle,
        trust_abort=bool(row.get("trust_abort")),
        receipt_signature_valid=sig_ok,
        source="code_receipts",
        source_path=source_path,
        run_id=str(row.get("ledger_sha") or row.get("receipt_sha") or "")[:32],
        tier=TrajectoryTier.BRONZE.value,
        skill_tags=_skill_tags_from_receipt(row),
        training_permitted=not bool(row.get("demo")),
        fixture_immutable=bool(row.get("fixture_immutable", True)),
        harvested_at=int(time.time()),
    )
    t.compute_id()
    return t


def trajectory_from_agent_receipt(row: Dict[str, Any], source_path: str = "") -> Trajectory:
    task = str(row.get("task") or row.get("command") or row.get("prompt") or "")
    if not task and row.get("task_sha"):
        task = f"(redacted task sha={row.get('task_sha')[:16]})"
    verdict = str(row.get("verdict") or row.get("status") or "unknown")
    oracle = "pass" if verdict in ("verified", "pass", "green", "ok") else (
        "fail" if verdict in ("failed", "fail", "red", "false_green") else "unknown"
    )
    model = str(row.get("model") or row.get("writerModel") or row.get("winner") or "unknown")
    messages = [
        {"role": "user", "content": task or "(no task text)"},
        {"role": "assistant", "content": str(row.get("answer") or row.get("verdict") or "")},
    ]
    t = Trajectory(
        task=task,
        task_bucket=infer_bucket(task, str(row.get("mode") or row.get("action_kind") or "")),
        model=model,
        provider=str(row.get("provider") or ""),
        messages=messages,
        verification={
            "verdict": verdict,
            "status": row.get("status"),
            "math": row.get("math"),
            "u_fused": row.get("u_fused"),
        },
        independent_oracle=oracle,
        trust_abort=bool(row.get("trust_abort")),
        receipt_signature_valid=bool(row.get("receipt_sha") or row.get("receiptHash")),
        source="agent_receipts",
        source_path=source_path,
        run_id=str(row.get("receipt_sha") or row.get("receiptHash") or "")[:32],
        tier=TrajectoryTier.BRONZE.value,
        skill_tags=_skill_tags_from_receipt(row),
        harvested_at=int(time.time()),
    )
    t.compute_id()
    return t


def controller_step_to_traj(row: Dict[str, Any], source_path: str = "") -> Trajectory:
    """Wrap a single NFET control step as a minimal trajectory for controller builder."""
    state = row.get("state") or {}
    action = str(row.get("action") or "continue")
    ok = bool((row.get("outcome") or {}).get("exit_ok", True))
    t = Trajectory(
        task=f"control step: {action}",
        task_bucket="controller",
        model="nfet-controller",
        provider="local",
        messages=[
            {"role": "user", "content": f"state={state}"},
            {"role": "assistant", "content": action},
        ],
        actions_proposed=[{"type": action, "consumed": row.get("consumed")}],
        verification={"outcome": row.get("outcome") or {}, "ok": ok},
        independent_oracle="pass" if ok else "fail",
        receipt_signature_valid=True,  # local control log; not user content
        source="nfet_trajectories",
        source_path=source_path,
        run_id=str(row.get("run_id") or ""),
        tier=TrajectoryTier.BRONZE.value,
        skill_tags=["task_state"],
        fixture_immutable=True,
        privacy_cleared=True,
        harvested_at=int(time.time()),
    )
    # Stash full state for controller_builder
    t.actions_proposed[0]["state"] = state
    t.compute_id()
    return t


def harvest_repo(
    repo_root: Path,
    *,
    out_dir: Optional[Path] = None,
    secrets: Optional[Sequence[str]] = None,
    max_per_source: int = 5000,
) -> Dict[str, Any]:
    """Read known receipt logs → Bronze JSONL under runs/evolution/raw/."""
    repo_root = Path(repo_root)
    paths = default_paths(repo_root)
    out_dir = Path(out_dir) if out_dir else paths.raw
    out_dir.mkdir(parents=True, exist_ok=True)

    bronze: List[Trajectory] = []
    sources: Dict[str, int] = {}

    code_path = repo_root / "runs" / "code_receipts.jsonl"
    for row in read_jsonl(code_path)[-max_per_source:]:
        bronze.append(trajectory_from_code_receipt(row, str(code_path)))
    sources["code_receipts"] = len([t for t in bronze if t.source == "code_receipts"])

    # Also fold live dual-write stream (already privacy-scrubbed) as raw dicts
    stream_path = (repo_root / "runs" / "evolution" / "raw" / "bronze_stream.jsonl")
    if stream_path.exists():
        n0 = len(bronze)
        for row in read_jsonl(stream_path)[-max_per_source:]:
            bronze.append(Trajectory.from_dict(row))
        sources["bronze_stream"] = len(bronze) - n0

    for name in ("claude_receipts.jsonl", "agent_receipts.jsonl"):
        p = repo_root / "runs" / name
        n0 = len(bronze)
        for row in read_jsonl(p)[-max_per_source:]:
            bronze.append(trajectory_from_agent_receipt(row, str(p)))
        sources[name] = len(bronze) - n0

    nfet_path = repo_root / "runs" / "nfet_trajectories.jsonl"
    n0 = len(bronze)
    for row in read_jsonl(nfet_path)[-max_per_source:]:
        bronze.append(controller_step_to_traj(row, str(nfet_path)))
    sources["nfet_trajectories"] = len(bronze) - n0

    # Privacy scrub → write bronze
    cleaned_rows: List[Dict[str, Any]] = []
    residual_blocked = 0
    for t in bronze:
        d, report = clear_trajectory(t.to_dict(), secrets=secrets)
        d["tier"] = TrajectoryTier.BRONZE.value
        if not report["privacy_cleared"]:
            residual_blocked += 1
            d["privacy_cleared"] = False
        else:
            d["privacy_cleared"] = True
        cleaned_rows.append(d)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = out_dir / f"bronze_{stamp}.jsonl"
    write_jsonl(out_path, cleaned_rows)
    # also maintain a rolling "latest"
    write_jsonl(out_dir / "bronze_latest.jsonl", cleaned_rows)

    return {
        "bronze_path": str(out_path),
        "count": len(cleaned_rows),
        "sources": sources,
        "privacy_uncleared": residual_blocked,
        "ts": int(time.time()),
    }


def iter_trajectories(path: Path) -> Iterable[Trajectory]:
    for row in read_jsonl(path):
        yield Trajectory.from_dict(row)
