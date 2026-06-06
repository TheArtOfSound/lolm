"""Persistent local memory for LOLM-NFET.

Python port of the useful Hellhound memory pattern:
- memory.jsonl: append-only notes
- identity.md: durable identity/project facts
- summaries.jsonl: rolling summaries
- goals.json: explicit active objectives
- journal.md: periodic self-reflection journal
- sessions/: archived chat sessions
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MemoryPaths:
    root: Path

    @property
    def notes(self) -> Path:
        return self.root / "memory.jsonl"

    @property
    def identity(self) -> Path:
        return self.root / "identity.md"

    @property
    def summaries(self) -> Path:
        return self.root / "summaries.jsonl"

    @property
    def goals(self) -> Path:
        return self.root / "goals.json"

    @property
    def journal(self) -> Path:
        return self.root / "journal.md"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"


class MemoryStore:
    def __init__(self, root: Path):
        self.paths = MemoryPaths(root=root)
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.sessions.mkdir(parents=True, exist_ok=True)

    def _append_line(self, path: Path, row: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def append_note(self, text: str, tag: str = "note", importance: int = 3) -> str:
        item_id = uuid.uuid4().hex[:8]
        self._append_line(self.paths.notes, {
            "id": item_id,
            "ts": time.time(),
            "tag": tag,
            "importance": importance,
            "text": text,
        })
        return item_id

    def recent_notes(self, limit: int = 8, min_importance: int = 0) -> List[Dict[str, Any]]:
        rows = [r for r in self._read_jsonl(self.paths.notes) if int(r.get("importance", 0)) >= min_importance]
        return rows[-limit:]

    def search_notes(self, query: str, limit: int = 12, min_importance: int = 0, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        tokens = [t for t in re.split(r"\W+", query.lower()) if t]
        hits: List[Dict[str, Any]] = []
        for row in reversed(self._read_jsonl(self.paths.notes)):
            if int(row.get("importance", 0)) < min_importance:
                continue
            if tag and row.get("tag") != tag:
                continue
            hay = json.dumps(row, ensure_ascii=False).lower()
            if tokens and not all(t in hay for t in tokens):
                continue
            hits.append(row)
            if len(hits) >= limit:
                break
        return hits

    def read_identity(self) -> str:
        return self.paths.identity.read_text(encoding="utf-8") if self.paths.identity.exists() else ""

    def append_identity_line(self, line: str) -> None:
        clean = line.strip()
        if not clean:
            return
        existing = self.read_identity()
        bullet = f"- {clean}"
        if bullet in existing:
            return
        if not existing:
            existing = "# Local identity and durable facts\n\n"
        if not existing.endswith("\n"):
            existing += "\n"
        self.paths.identity.write_text(existing + bullet + "\n", encoding="utf-8")

    def add_summary(self, summary: str, span: str = "session") -> None:
        self._append_line(self.paths.summaries, {"ts": time.time(), "span": span, "summary": summary})

    def recent_summaries(self, limit: int = 5) -> List[Dict[str, Any]]:
        return self._read_jsonl(self.paths.summaries)[-limit:]

    def append_journal(self, markdown: str) -> None:
        header = time.strftime("\n\n## %Y-%m-%d %H:%M:%S\n\n")
        if not self.paths.journal.exists():
            self.paths.journal.write_text("# LOLM-NFET running journal\n", encoding="utf-8")
        with self.paths.journal.open("a", encoding="utf-8") as handle:
            handle.write(header + markdown.strip() + "\n")

    def read_journal(self, max_chars: int = 8000) -> str:
        raw = self.paths.journal.read_text(encoding="utf-8") if self.paths.journal.exists() else ""
        return raw[-max_chars:]

    def get_goals(self) -> List[Dict[str, Any]]:
        if not self.paths.goals.exists():
            return []
        try:
            data = json.loads(self.paths.goals.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def set_goals(self, goals: List[Dict[str, Any]]) -> None:
        self.paths.goals.write_text(json.dumps(goals, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_goal(self, title: str, why: str = "", priority: int = 3) -> str:
        item_id = uuid.uuid4().hex[:8]
        goals = self.get_goals()
        goals.append({"id": item_id, "title": title, "why": why, "priority": priority, "status": "active", "ts": time.time()})
        self.set_goals(goals)
        return item_id

    def update_goal(self, item_id: str, **patch: Any) -> bool:
        goals = self.get_goals()
        for goal in goals:
            if goal.get("id") == item_id:
                goal.update({k: v for k, v in patch.items() if v is not None})
                self.set_goals(goals)
                return True
        return False

    def save_session(self, turns: List[Dict[str, Any]], title: str = "session") -> str:
        item_id = uuid.uuid4().hex[:8]
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", title.strip() or "session")[:80]
        path = self.paths.sessions / f"{int(time.time())}-{safe}-{item_id}.json"
        path.write_text(json.dumps({"id": item_id, "ts": time.time(), "title": title, "turns": turns}, indent=2, ensure_ascii=False), encoding="utf-8")
        return item_id
