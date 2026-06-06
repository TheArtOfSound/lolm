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


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


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

    identity_path = data_dir / "identity.md"
    if identity_path.exists():
        identity = identity_path.read_text(encoding="utf-8").strip()
        if identity:
            lines.append("\n--- durable identity / project facts ---")
            lines.append(identity[-2500:])

    goals = _read_json(data_dir / "goals.json")
    if isinstance(goals, list):
        active = [g for g in goals if g.get("status", "active") == "active"]
        if active:
            lines.append("\n--- active goals ---")
            for g in sorted(active, key=lambda x: x.get("priority", 3), reverse=True)[-8:]:
                lines.append(f"[{g.get('id', '?')}] {g.get('title', '')} — {g.get('why', '')}")

    memory = _read_jsonl(data_dir / "memory.jsonl", limit=8)
    if memory:
        lines.append("\n--- local memory notes ---")
        for m in memory:
            lines.append(f"• {m.get('text', m.get('content', ''))}")

    summaries = _read_jsonl(data_dir / "summaries.jsonl", limit=5)
    if summaries:
        lines.append("\n--- rolling summaries ---")
        for s in summaries:
            lines.append(f"[{s.get('span', 'summary')}] {s.get('summary', '')}")

    recent_state = _latest_chat_summaries(data_dir)
    if recent_state:
        lines.append("\n--- recent LOLM/NFET state summaries ---")
        lines.extend(recent_state)

    journal_path = data_dir / "journal.md"
    if journal_path.exists():
        journal = journal_path.read_text(encoding="utf-8").strip()
        if journal:
            lines.append("\n--- recent running journal ---")
            lines.append(journal[-2500:])

    lines.append("=== END_AUTO_CONTEXT ===")
    return "\n".join(lines)
