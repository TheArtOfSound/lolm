# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Immediate rollback to previous_known_good adapter."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from lolm.evolution.registry import default_registry
from lolm.evolution.schema import default_paths


def rollback_to_previous(repo_root: Path, *, reason: str = "") -> Dict[str, Any]:
    """Swap live ← previous_known_good. Fails closed if previous missing."""
    repo_root = Path(repo_root)
    paths = default_paths(repo_root)
    prev = paths.previous / "adapter"
    live = paths.live / "adapter"

    if not prev.exists() or not any(prev.iterdir()):
        return {
            "decision": "rollback_failed",
            "reason": "previous_known_good missing",
        }

    # Park the failed live as candidates/rolled_back_<ts>
    if live.exists() and any(live.iterdir()):
        park = paths.candidates / f"rolled_back_{int(time.time())}"
        if park.exists():
            shutil.rmtree(park)
        shutil.copytree(live, park)
        if (paths.live / "manifest.json").exists():
            shutil.copy2(paths.live / "manifest.json", park / "manifest.json")

    if live.exists():
        shutil.rmtree(live)
    shutil.copytree(prev, live)
    if (paths.previous / "manifest.json").exists():
        shutil.copy2(paths.previous / "manifest.json", paths.live / "manifest.json")

    man: Dict[str, Any] = {}
    if (paths.live / "manifest.json").exists():
        try:
            man = json.loads((paths.live / "manifest.json").read_text())
        except json.JSONDecodeError:
            man = {}
    version = man.get("model_version") or "previous_known_good"
    (paths.live / "CURRENT").write_text(version + "\n")

    receipt = {
        "event": "rollback",
        "model_version": version,
        "reason": reason or "operator_or_gate",
        "ts": int(time.time()),
        "decision": "rolled_back",
    }
    from lolm.evolution.schema import append_jsonl
    append_jsonl(paths.receipts / "promote.jsonl", receipt)
    reg = default_registry(repo_root)
    reg.append({
        "model_version": version,
        "decision": "rolled_back",
        "notes": reason,
        "ts": receipt["ts"],
        "base_model": man.get("base_model") or "",
    })
    return receipt
