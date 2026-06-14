# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Durable tick scheduler — the 'scheduling' subsystem of a persistent agent.

The agent can schedule a future tick (when the controller chooses ``schedule``),
and a runner pops the due ones. A JSONL queue keeps it inspectable and crash-
safe; nothing here runs anything itself — it only records intent and reports
what is due, so scheduling stays bounded and auditable.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class TickScheduler:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def schedule(self, agent_id: str, trigger: str = "scheduled_tick",
                 run_after_ms: float = 0.0, reason: str = "",
                 now_ms: Optional[float] = None) -> str:
        sid = f"sch-{uuid.uuid4().hex[:12]}"
        base = now_ms if now_ms is not None else time.time() * 1000.0
        row = {"id": sid, "agentId": agent_id, "trigger": trigger,
               "runAt": base + max(0.0, run_after_ms), "reason": reason[:200],
               "done": False, "createdAt": int(base)}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return sid

    def _read(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            with self.path.open() as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        # Last write wins per id (so mark_done overrides).
        latest: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            latest[r.get("id")] = r
        return list(latest.values())

    def due(self, now_ms: Optional[float] = None) -> List[Dict[str, Any]]:
        now = now_ms if now_ms is not None else time.time() * 1000.0
        return [r for r in self._read() if not r.get("done") and r.get("runAt", 0) <= now]

    def pending(self) -> List[Dict[str, Any]]:
        return [r for r in self._read() if not r.get("done")]

    def mark_done(self, sid: str) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps({"id": sid, "done": True,
                                    "at": int(time.time() * 1000)}) + "\n")
