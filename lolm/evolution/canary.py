# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Canary traffic split: incumbent vs candidate without user-visible risk.

``canary_pct`` from live/manifest.json — fraction of eligible requests that
should use the candidate adapter. Shadow-only mode (pct=0) never serves candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from lolm.evolution.schema import default_paths

CANARY_STAGES = (0.05, 0.25, 0.50, 1.0)


def load_live_manifest(repo_root: Path) -> Dict[str, Any]:
    p = default_paths(repo_root).live / "manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def select_adapter(
    repo_root: Path,
    *,
    request_id: str = "",
    force: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Return (adapter_path or "", meta).

    force: "live" | "previous" | "none" | None
    """
    paths = default_paths(repo_root)
    live = paths.live / "adapter"
    prev = paths.previous / "adapter"
    man = load_live_manifest(repo_root)
    pct = float(man.get("canary_pct") or os.environ.get("LOLM_CANARY_PCT") or 0.0)
    decision = str(man.get("decision") or "")

    live_ok = (live / "adapters.safetensors").exists()
    prev_ok = (prev / "adapters.safetensors").exists()

    if force == "none":
        return "", {"served": "base", "canary_pct": pct}
    if force == "previous" and prev_ok:
        return str(prev), {"served": "previous_known_good", "canary_pct": pct}
    if force == "live" and live_ok:
        return str(live), {"served": "live", "canary_pct": pct}

    # Full promote
    if decision == "promoted" or pct >= 1.0:
        if live_ok:
            return str(live), {"served": "live", "canary_pct": 1.0}
        return "", {"served": "base", "canary_pct": pct}

    # Canary: deterministic hash of request_id
    if live_ok and pct > 0:
        rid = request_id or str(time.time())
        h = int(hashlib.sha256(rid.encode()).hexdigest()[:8], 16)
        if (h % 10000) / 10000.0 < pct:
            return str(live), {"served": "canary", "canary_pct": pct}
        if prev_ok:
            return str(prev), {"served": "incumbent", "canary_pct": pct}
        # no previous — fall back to live only if canary, else base
        return "", {"served": "base_incumbent", "canary_pct": pct}

    if prev_ok:
        return str(prev), {"served": "previous_known_good", "canary_pct": pct}
    if live_ok:
        return str(live), {"served": "live", "canary_pct": pct}
    return "", {"served": "base", "canary_pct": pct}


def next_canary_stage(current: float) -> float:
    for s in CANARY_STAGES:
        if current + 1e-9 < s:
            return s
    return 1.0


def advance_canary(
    repo_root: Path,
    *,
    eval_ok: bool,
    shadow_win_rate: float = 0.0,
    min_win_rate: float = 0.52,
) -> Dict[str, Any]:
    """Bump canary % when offline+shadow still healthy; freeze/rollback signal otherwise."""
    paths = default_paths(repo_root)
    man_path = paths.live / "manifest.json"
    man = load_live_manifest(repo_root)
    if not man:
        return {"advanced": False, "reason": "no_live_manifest"}
    cur = float(man.get("canary_pct") or 0.0)
    if not eval_ok or shadow_win_rate < min_win_rate:
        return {
            "advanced": False,
            "reason": "gates_not_met",
            "canary_pct": cur,
            "recommend_rollback": cur > 0 and shadow_win_rate < 0.45,
        }
    nxt = next_canary_stage(cur)
    if nxt <= cur + 1e-9:
        man["decision"] = "promoted"
        man["canary_pct"] = 1.0
        man_path.write_text(json.dumps(man, indent=2))
        return {"advanced": False, "reason": "already_full", "canary_pct": 1.0, "decision": "promoted"}
    man["canary_pct"] = nxt
    man["decision"] = "promoted" if nxt >= 1.0 else "canary"
    man["canary_advanced_ts"] = int(time.time())
    man_path.write_text(json.dumps(man, indent=2))
    from lolm.evolution.registry import default_registry
    default_registry(repo_root).append(man)
    return {"advanced": True, "canary_pct": nxt, "decision": man["decision"]}
