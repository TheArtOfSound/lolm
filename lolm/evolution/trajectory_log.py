# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Dual-write product receipts into full evolution trajectories.

Called from ``local_ui.code_receipts.append`` so every sealed code/visual run
feeds Bronze without a separate harvest-only path.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lolm.evolution.privacy import clear_trajectory
from lolm.evolution.schema import Trajectory, TrajectoryTier, append_jsonl, default_paths


def _messages_from_trail(task: str, trail: List[Dict[str, Any]], verdict: str, ok: bool) -> List[Dict[str, str]]:
    msgs: List[Dict[str, str]] = [{"role": "user", "content": task or "(no task)"}]
    for step in trail or []:
        op = str(step.get("op") or "")
        if op == "read":
            msgs.append({"role": "assistant", "content": f"READ: {step.get('path')}"})
            msgs.append({"role": "tool", "content": f"read {step.get('path')} ({step.get('bytes')} bytes)"})
        elif op == "write":
            msgs.append({"role": "assistant", "content": f"EDIT/WRITE: {step.get('path')}"})
            msgs.append({"role": "tool", "content": f"wrote {step.get('path')} ({step.get('bytes')} bytes)"})
        elif op == "edit":
            msgs.append({"role": "assistant", "content": f"EDIT: {step.get('path')} ok={step.get('ok')}"})
            msgs.append({"role": "tool", "content": str(step.get("note") or f"edit {step.get('path')}")})
        elif op in ("run", "verify"):
            cmd = step.get("command") or ""
            msgs.append({"role": "assistant", "content": f"{'VERIFY' if op == 'verify' else 'RUN'}: {cmd}"})
            out = (step.get("stdout_tail") or "")[:200]
            err = (step.get("stderr_tail") or "")[:200]
            msgs.append({
                "role": "tool",
                "content": f"exit={step.get('exit')} stdout={out!r} stderr={err!r}",
            })
        elif op == "list":
            msgs.append({"role": "assistant", "content": "LIST workspace"})
            msgs.append({"role": "tool", "content": f"n={step.get('n')}"})
    done = "DONE: verified" if ok else f"INCOMPLETE: {verdict}"
    msgs.append({"role": "assistant", "content": done})
    return msgs


def receipt_to_trajectory(row: Dict[str, Any], *, source: str = "code_receipts") -> Trajectory:
    """Expand a sealed code/visual receipt into a train-ready Trajectory skeleton."""
    task = str(row.get("task") or row.get("summary") or "")
    trail = list(row.get("trail") or [])
    ok = bool(row.get("ok") or row.get("verified") or row.get("verdict") in ("verified", "shipped"))
    verdict = str(row.get("verdict") or ("pass" if ok else "fail"))
    files = list(row.get("files") or [])
    files_read = [t.get("path") for t in trail if t.get("op") == "read" and t.get("path")]
    mutations = [
        {"op": t.get("op"), "path": t.get("path"), "ok": t.get("ok")}
        for t in trail if t.get("op") in ("write", "edit")
    ]
    commands = [str(t.get("command") or "") for t in trail if t.get("op") in ("run", "verify")]
    stdout = [str(t.get("stdout_tail") or "") for t in trail if t.get("stdout_tail")]
    stderr = [str(t.get("stderr_tail") or "") for t in trail if t.get("stderr_tail")]
    model = str(
        row.get("winner") or row.get("model") or row.get("writerModel")
        or (row.get("nfet") or {}).get("model") or "unknown"
    )
    # Signature: Ed25519 seal or hash chain
    sig_ok = bool(
        row.get("receipt_signature") or row.get("signature")
        or row.get("receipt_sha") or row.get("ledger_sha")
    )
    ver = row.get("verification") if isinstance(row.get("verification"), dict) else {}
    skill_tags: List[str] = ["tool_use"]
    if files_read or any(t.get("op") == "read" for t in trail):
        skill_tags.append("read_before_edit")
    if any(t.get("op") == "verify" for t in trail) or (row.get("verifies") or 0) > 0:
        skill_tags.append("verify_work")
    if ok:
        skill_tags.append("avoid_false_completion")
    if (row.get("failed_runs") or 0) >= 1 and ok:
        skill_tags.append("patch_recovery")
    if row.get("trust_abort"):
        skill_tags.append("abstain")

    # Bucket
    from lolm.evolution.harvest import infer_bucket
    bucket = infer_bucket(task, str(row.get("kind") or ""))

    t = Trajectory(
        task=task,
        task_bucket=bucket,
        model=model if model != "unknown" else str(row.get("source") or "code_agent"),
        provider=str(row.get("provider") or row.get("source") or ""),
        messages=_messages_from_trail(task, trail, verdict, ok),
        files_read=[str(p) for p in files_read if p],
        actions_proposed=[{"trail": trail[:24]}],
        mutations_applied=mutations,
        commands_run=[c for c in commands if c],
        stdout=stdout,
        stderr=stderr,
        verification={
            **(ver or {}),
            "verdict": verdict,
            "ok": ok,
            "green_runs": row.get("green_runs"),
            "failed_runs": row.get("failed_runs"),
            "verifies": row.get("verifies"),
            "expected_ok": row.get("expected_ok"),
            "syntax_ok": row.get("syntax_ok"),
        },
        final_tree_hash=str(
            row.get("tree_hash") or row.get("workspace_tree_hash")
            or (ver or {}).get("workspace_tree_sha256") or row.get("html_sha") or ""
        ),
        independent_oracle="pass" if ok else "fail",
        trust_abort=bool(row.get("trust_abort")),
        receipt_signature_valid=sig_ok,
        source=source,
        source_path=str(row.get("source") or ""),
        run_id=str(row.get("run_id") or row.get("receipt_sha") or row.get("ledger_sha") or "")[:48],
        tier=TrajectoryTier.BRONZE.value,
        skill_tags=sorted(set(skill_tags)),
        training_permitted=not bool(row.get("demo")),
        fixture_immutable=True,
        privacy_cleared=False,  # set after scrub
        harvested_at=int(time.time()),
    )
    # Prefer model name from sealed identity
    if t.model in ("unknown", "") and files:
        t.model = "code_agent"
    t.compute_id()
    return t


def dual_write_receipt(
    row: Dict[str, Any],
    *,
    repo_root: Optional[Path] = None,
    source: str = "code_receipts",
) -> Optional[Dict[str, Any]]:
    """Privacy-scrub and append one Bronze trajectory. Never raises into product path."""
    try:
        if row.get("demo") and not row.get("selftest"):
            return None  # do not train on pure demo seeds
        repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        paths = default_paths(repo_root)
        traj = receipt_to_trajectory(row, source=source)
        cleaned, report = clear_trajectory(traj.to_dict())
        cleaned["privacy_cleared"] = report.get("privacy_cleared", False)
        cleaned["tier"] = TrajectoryTier.BRONZE.value
        # Rolling bronze stream + daily file
        append_jsonl(paths.raw / "bronze_stream.jsonl", cleaned)
        day = time.strftime("%Y%m%d", time.gmtime())
        append_jsonl(paths.raw / f"bronze_{day}.jsonl", cleaned)
        return {"trajectory_id": cleaned.get("trajectory_id"), "privacy_cleared": cleaned["privacy_cleared"]}
    except Exception as exc:
        return {"error": str(exc)[:200]}
