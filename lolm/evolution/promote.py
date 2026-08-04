# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Gated promotion with canary stages and previous_known_good retention.

Never overwrite last known good on a failed candidate. Live pointers:
  live/adapter          — current serving adapter
  previous/adapter      — previous_known_good
  candidates/<version>  — immutable candidate artifacts
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from lolm.evolution.registry import ModelRegistry, default_registry
from lolm.evolution.schema import ModelManifest, default_paths

# Canary ladder — do not jump to 100% on first offline pass.
CANARY_STAGES = (0.0, 0.05, 0.25, 0.50, 1.0)


def _copy_adapter(src: Path, dst: Path) -> None:
    dst = Path(dst)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def promote_candidate(
    repo_root: Path,
    candidate_dir: Path,
    eval_result: Dict[str, Any],
    *,
    canary_pct: float = 0.05,
    force: bool = False,
    registry: Optional[ModelRegistry] = None,
) -> Dict[str, Any]:
    """Promote candidate → live (after backing up previous).

    Requires eval_result.promote_ready or offline_ok with canary_pct < 1.
    Full 100% promote requires promote_ready when shadow was required.
    """
    repo_root = Path(repo_root)
    cand = Path(candidate_dir)
    paths = default_paths(repo_root)
    reg = registry or default_registry(repo_root)

    offline_ok = bool(eval_result.get("offline_ok"))
    promote_ready = bool(eval_result.get("promote_ready"))
    if not force:
        if canary_pct >= 1.0 and not promote_ready and not offline_ok:
            return {
                "decision": "rejected",
                "reason": "gates failed for full promotion",
                "eval": eval_result.get("decision"),
            }
        if not offline_ok:
            return {
                "decision": "rejected",
                "reason": "offline gates failed",
                "eval": eval_result.get("decision"),
            }
        if canary_pct >= 1.0 and eval_result.get("decision") == "rejected_shadow":
            return {
                "decision": "rejected",
                "reason": "shadow gate failed; cannot go to 100%",
            }

    man_path = cand / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    version = man.get("model_version") or cand.name

    live = paths.live / "adapter"
    prev = paths.previous / "adapter"
    live_man = paths.live / "manifest.json"

    # Preserve previous_known_good
    if live.exists() and any(live.iterdir()):
        _copy_adapter(live, prev)
        if live_man.exists():
            shutil.copy2(live_man, paths.previous / "manifest.json")

    _copy_adapter(cand, live)

    man["decision"] = "promoted" if canary_pct >= 1.0 else "canary"
    man["canary_pct"] = canary_pct
    man["offline_score_before"] = eval_result.get("offline_score_before", 0.0)
    man["offline_score_after"] = eval_result.get("offline_score_after", 0.0)
    man["shadow_wins"] = (eval_result.get("gates") or {}).get("shadow_traffic", {}).get("checks", [])
    # flatten shadow scores if present
    shadow = (eval_result.get("gates") or {}).get("shadow_traffic") or {}
    man["trust_aborts"] = 0
    if "score" in shadow:
        # win rate stored as score in gate
        pass
    man["gates"] = eval_result.get("gates") or {}
    man["ts"] = int(time.time())

    # pull shadow wins/losses from latest shadow receipt if any
    shadow_latest = paths.receipts / "shadow_latest.json"
    if shadow_latest.exists():
        try:
            s = json.loads(shadow_latest.read_text())
            man["shadow_wins"] = s.get("shadow_wins", 0)
            man["shadow_losses"] = s.get("shadow_losses", 0)
        except json.JSONDecodeError:
            pass

    live_man.write_text(json.dumps(man, indent=2))
    reg.append(man)

    from lolm.evolution.schema import append_jsonl
    receipt = {
        "event": "promote",
        "model_version": version,
        "canary_pct": canary_pct,
        "decision": man["decision"],
        "previous_version": man.get("previous_version") or "",
        "adapter_sha256": man.get("adapter_sha256"),
        "ts": man["ts"],
    }
    append_jsonl(paths.receipts / "promote.jsonl", receipt)

    # Pointer files for operators
    (paths.live / "CURRENT").write_text(version + "\n")
    if (paths.previous / "manifest.json").exists():
        try:
            pv = json.loads((paths.previous / "manifest.json").read_text()).get("model_version", "")
            (paths.previous / "PREVIOUS_KNOWN_GOOD").write_text(pv + "\n")
        except json.JSONDecodeError:
            pass

    return {
        "decision": man["decision"],
        "model_version": version,
        "canary_pct": canary_pct,
        "live_adapter": str(live),
        "previous_adapter": str(prev) if prev.exists() else "",
        "receipt": receipt,
    }


def reject_candidate(
    repo_root: Path,
    candidate_dir: Path,
    eval_result: Dict[str, Any],
    *,
    registry: Optional[ModelRegistry] = None,
) -> Dict[str, Any]:
    cand = Path(candidate_dir)
    paths = default_paths(repo_root)
    reg = registry or default_registry(repo_root)
    man: Dict[str, Any] = {}
    if (cand / "manifest.json").exists():
        man = json.loads((cand / "manifest.json").read_text())
    man["decision"] = "rejected"
    man["gates"] = eval_result.get("gates") or {}
    man["ts"] = int(time.time())
    (cand / "manifest.json").write_text(json.dumps(man, indent=2))
    reg.append(man)
    return {"decision": "rejected", "model_version": man.get("model_version") or cand.name}
