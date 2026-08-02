# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Frozen fixture packages for Track 2B (single source of truth)."""

from __future__ import annotations

import secrets
from typing import Any, Dict, List, Mapping, Tuple

from lolm.track2b.workspace import tree_hash

MAX_FIXTURE_BYTES = 1_500_000  # pre-transmission hard cap
MAX_PATH_LEN = 200


def fixture_hash(seed_files: Mapping[str, str]) -> str:
    return tree_hash(dict(seed_files or {}))


def validate_fixture_paths(seed_files: Mapping[str, str]) -> List[str]:
    """Return rejection reasons (empty = ok)."""
    reasons: List[str] = []
    total = 0
    for path, body in (seed_files or {}).items():
        p = (path or "").replace("\\", "/")
        if not p or p.startswith("/") or p.startswith("~"):
            reasons.append(f"absolute_or_empty:{path!r}")
            continue
        parts = p.split("/")
        if any(part in ("", ".", "..") for part in parts):
            reasons.append(f"path_traversal:{path!r}")
            continue
        if len(p) > MAX_PATH_LEN:
            reasons.append(f"path_too_long:{path!r}")
        if "\x00" in p or "\x00" in (body or ""):
            reasons.append(f"nul_byte:{path!r}")
        total += len((body or "").encode("utf-8", errors="replace"))
    if total > MAX_FIXTURE_BYTES:
        reasons.append(f"fixture_too_large:{total}>{MAX_FIXTURE_BYTES}")
    return reasons


def build_resume_package(
    task_id: str,
    task_text: str,
    seed_files: Mapping[str, str],
    *,
    session_id: str = "",
    conversation_id: str = "",
) -> Dict[str, Any]:
    """Generate resume_package from frozen fixture manifest (no hand-maintained copy)."""
    reasons = validate_fixture_paths(seed_files)
    if reasons:
        raise ValueError("invalid_fixture:" + ",".join(reasons[:6]))
    fhash = fixture_hash(seed_files)
    nonce = secrets.token_hex(4)
    sid = session_id or f"track2b-{task_id}-{nonce}"
    cid = conversation_id or f"track2b-{task_id}"
    # workspace_snapshot is the sole fixture body source
    snapshot = {k: v for k, v in seed_files.items()}
    return {
        "resume_token": f"benchmark:{task_id}:{fhash}",
        "run_id": f"fixture-{task_id}",
        "task": task_text,
        "status": "benchmark_fixture",
        "checkpoint_id": f"fixture:{fhash}",
        "workspace_snapshot": snapshot,
        "reliability_snapshot": {},
        "failure_ledger": {},
        "contract_snapshot": {},
        "checkpoint_payload": {},
        "event_cursor": 0,
        "session_id": sid,
        "conversation_id": cid,
        "fixture_hash": fhash,
        "task_id": task_id,
    }


def build_sse_request(
    task_id: str,
    task_text: str,
    seed_files: Mapping[str, str],
    *,
    max_steps: int = 28,
) -> Dict[str, Any]:
    pkg = build_resume_package(task_id, task_text, seed_files)
    return {
        "task": task_text,
        "max_steps": max_steps,
        "session_id": pkg["session_id"],
        "conversation_id": pkg["conversation_id"],
        "context_reset": True,
        "resume_package": pkg,
    }
