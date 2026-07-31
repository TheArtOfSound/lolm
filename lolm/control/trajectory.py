# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Control-trajectory logging for offline training / counterfactuals.

Each step: (s_t, a_t, consumed, cost_proxy, outcome_proxy).
JSONL append-only under runs/nfet_trajectories.jsonl by default.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.Lock()
_PATH: Optional[Path] = None


def init(path: Optional[Path] = None) -> Path:
    global _PATH
    if path is None:
        env = os.environ.get("LOLM_NFET_TRAJECTORY", "").strip()
        path = Path(env) if env else (
            Path(__file__).resolve().parent.parent.parent / "runs" / "nfet_trajectories.jsonl"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _PATH = path
    return path


def path() -> Path:
    return _PATH or init()


def log_step(
    *,
    state: Dict[str, Any],
    action: str,
    consumed: bool,
    cost: float = 0.0,
    outcome: Optional[Dict[str, Any]] = None,
    run_id: str = "",
    source: str = "code",
) -> Dict[str, Any]:
    row = {
        "ts": int(time.time()),
        "run_id": run_id,
        "source": source,
        "state": state,
        "action": action,
        "consumed": bool(consumed),
        "cost": float(cost),
        "outcome": outcome or {},
    }
    p = path()
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _LOCK:
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    return row


def tail(limit: int = 50) -> List[Dict[str, Any]]:
    p = path()
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines[-max(1, limit):]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out
