"""Auto-context builder for the local LOLM-NFET workspace.

Inspired by Hellhound's AutoContext.swift: every request gets a compact
snapshot of what is true now, plus local memory and goals. This makes the
assistant feel continuous instead of stateless.
"""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Dict, List


def _read_jsonl(path: Path, limit: int = 20) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _latest_chat_summaries(data_dir: Path, limit: int = 3) -> List[str]:
    log = data_dir / "improvement_log.jsonl"
    items = _read_jsonl(log, limit=200)
    chats = [x for x in items if x.get("type") == "chat"][-limit:]
    rows: List[str] = []
    for item in chats:
        summary = item.get("summary", {}) or {}
        rows.append(
            f"chat {item.get('id')}: tokens={item.get('tokens')} "
            f"graft={item.get('use_graft')} gate={summary.get('avg_gate')} "
            f"latent={summary.get('avg_latent_share')} control={summary.get('last_control')}"
        )
    return rows


def build_auto_context(data_dir: Path) -> str:
    lines: List[str] = []
    lines.append(f"=== AUTO_CONTEXT @ {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    lines.append(f"host: {platform.node() or '?'}")
    lines.append(f"platform: {platform.platform()}")
    lines.append(f"cwd: {os.getcwd()}")
    lines.append(f"timezone: {time.tzname[0] if time.tzname else '?'}")

    goals_path = data_dir / "goals.jsonl"
    goals = [g for g in _read_jsonl(goals_path, limit=50) if g.get("status", "active") == "active"]
    if goals:
        lines.append("\n--- active goals ---")
        for g in goals[-8:]:
            lines.append(f"[{g.get('id', '?')}] {g.get('title', '')} — {g.get('why', '')}")

    memory_path = data_dir / "memory.jsonl"
    memory = _read_jsonl(memory_path, limit=8)
    if memory:
        lines.append("\n--- local memory ---")
        for m in memory:
            lines.append(f"• {m.get('text', m.get('content', ''))}")

    summaries = _latest_chat_summaries(data_dir)
    if summaries:
        lines.append("\n--- recent LOLM/NFET state summaries ---")
        lines.extend(summaries)

    lines.append("=== END_AUTO_CONTEXT ===")
    return "\n".join(lines)
