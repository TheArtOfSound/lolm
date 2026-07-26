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

# Stopwords dropped from a query before relevance matching, so retrieval keys on
# the meaningful words ("carbonara", "flux") not the glue ("the", "how", "is").
_MEM_STOP = frozenset((
    "a an the and or but of to in on at is are was were be been being has have had it its "
    "as by for with that this these those from into than then so such which who whom whose "
    "will would can could may might must do does did not no they them their he she his her "
    "we our you your i me my one about over under more less most least very also just only "
    "per each any all some what how why when where does whats").split())


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

    def append_note(self, text: str, tag: str = "note", importance: int = 3,
                    scope: str = "global") -> str:
        # scope="global" (default) → visible to everyone; a session/conversation id
        # → visible ONLY when that scope is retrieving, so one visitor auto-teaching
        # a fact can't poison the shared store for others.
        item_id = uuid.uuid4().hex[:8]
        self._append_line(self.paths.notes, {
            "id": item_id,
            "ts": time.time(),
            "tag": tag,
            "importance": importance,
            "scope": scope or "global",
            "text": text,
        })
        return item_id

    def recent_notes(self, limit: int = 8, min_importance: int = 0) -> List[Dict[str, Any]]:
        rows = [r for r in self._read_jsonl(self.paths.notes) if int(r.get("importance", 0)) >= min_importance]
        return rows[-limit:]

    def search_notes(self, query: str, limit: int = 12, min_importance: int = 0,
                     tag: Optional[str] = None, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        """Relevance-scored retrieval. The old version AND-matched EVERY query token,
        so a note only surfaced when the prompt repeated its exact words — accrued
        knowledge almost never reached an answer. Now we score by how many CONTENT
        words overlap (weighted by coverage, importance, recency) and return the most
        relevant, so a RELATED question still finds what was learned. Requires a
        genuine overlap (>=2 content words, or full coverage of a short query) so it
        stays relevant, not a firehose."""
        q_tokens = [t for t in re.split(r"\W+", (query or "").lower()) if t]
        content = list({t for t in q_tokens if len(t) >= 3 and t not in _MEM_STOP})
        rows = [r for r in self._read_jsonl(self.paths.notes)
                if int(r.get("importance", 0)) >= min_importance
                and (not tag or r.get("tag") == tag)
                # ISOLATION: a scoped search sees only global notes + its own scope;
                # another visitor's session-scoped facts are invisible. Unscoped
                # search (scope=None) keeps legacy behaviour (everything visible).
                and (scope is None or r.get("scope", "global") in ("global", scope))]
        if not content:                               # no usable query → most recent
            return rows[-limit:]
        n = max(len(rows), 1)
        scored: List[Any] = []
        for idx, row in enumerate(rows):
            hay = json.dumps(row, ensure_ascii=False).lower()
            overlap = sum(1 for t in content if t in hay)
            if not overlap:
                continue
            coverage = overlap / len(content)
            # relevant if: 2+ content words overlap, OR half the query is covered,
            # OR a single DISTINCTIVE (long, rare) term matches — "carbonara",
            # "quantum" alone are strong signals; "flux" needs a second word.
            # Also: short follow-up queries (1 content token, 4+ chars) may match
            # a single clear term so "my name?" still finds "User is named Bryan".
            distinctive = any(len(t) >= 7 and t in hay for t in content)
            short_ok = len(content) == 1 and len(content[0]) >= 4 and content[0] in hay
            if overlap < 2 and coverage < 0.5 and not distinctive and not short_ok:
                continue
            score = (overlap + 1.5 * coverage
                     + 0.3 * int(row.get("importance", 3))
                     + 0.2 * (idx / n)                # gentle recency nudge
                     + (0.6 if (scope and row.get("scope") == scope) else 0)  # my own context first
                     + (0.4 if short_ok else 0))
            scored.append((score, row))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [row for _, row in scored[:limit]]

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

    def add_summary(self, summary: str, span: str = "session",
                    *, promote: bool = False) -> None:
        text = (summary or "").strip()
        if not text:
            return
        self._append_line(self.paths.summaries, {
            "ts": time.time(), "span": span, "summary": text, "promoted": bool(promote),
        })
        if promote:
            self.promote_summary_to_identity(text)

    def promote_summary_to_identity(self, summary: str) -> bool:
        """Lift durable user facts from a rolling summary into identity.md.

        Long-thread continuity: summaries alone age out of context windows;
        identity is always retrieved on identity-relevant turns. Only promote
        lines that look like durable personal/project facts — not every chitchat.
        """
        s = (summary or "").strip()
        if not s:
            return False
        # "user text → answer" rolling form from nfet_agent
        user_part = s.split(" → ", 1)[0].strip() if " → " in s else s
        low = user_part.lower()
        durable = (
            "remember", "my name", "i prefer", "i am ", "i'm ", "im ",
            "call me", "my timezone", "i work", "i live", "my project",
            "we use", "our stack", "don't ", "do not ", "always ", "never ",
        )
        if not any(m in low for m in durable):
            return False
        # Keep identity compact and non-duplicative
        line = re.sub(r"\s+", " ", user_part)[:160]
        if len(line) < 8:
            return False
        before = self.read_identity()
        self.append_identity_line(f"from chat: {line}")
        return self.read_identity() != before

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
