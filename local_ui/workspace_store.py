# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Persistent agent-workspace store — conversations, projects, runs, receipts.

The spine of LOLM-as-a-workbench rather than a one-shot demo: durable conversations
the user can reopen and continue, projects they can attach, and a receipt per agent
turn linking the model used, controller actions, memory, web searches, files touched
and the verdict. JSONL/JSON on disk (no external DB), mirroring the rest of the repo.

Phase 1 persists everything the existing real agent run already produces (messages,
receipts, memory, web sources). Sandbox command/file-change records have a schema
here but are written only when a real sandbox runs them — never faked.
"""

from __future__ import annotations

import json
import hashlib
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── data models (exactly the spec's shapes) ──────────────────────────────────
@dataclass
class Message:
    role: str                              # "user" | "assistant" | "system"
    content: str
    id: str = field(default_factory=lambda: _id("msg"))
    conversation_id: str = ""
    created_at: str = field(default_factory=_now)
    model_used: str = ""
    receipt_id: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)   # sources/memory/controls


@dataclass
class Conversation:
    title: str = "New conversation"
    id: str = field(default_factory=lambda: _id("conv"))
    owner_id: str = ""                     # immutable authenticated principal id
    project_id: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    archived: bool = False
    last_model_used: str = ""
    last_verdict: str = ""
    mode: str = "chat"
    messages: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Project:
    name: str
    owner_id: str
    id: str = field(default_factory=lambda: _id("proj"))
    repo_url: str = ""
    sandbox_id: str = ""
    framework: str = ""
    package_manager: str = ""
    scripts: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


# Sandbox records — schema only; written by a real sandbox, never fabricated.
@dataclass
class SandboxCommand:
    run_id: str
    command: str
    cwd: str = ""
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    id: str = field(default_factory=lambda: _id("cmd"))
    started_at: str = field(default_factory=_now)
    ended_at: str = ""


@dataclass
class FileChange:
    run_id: str
    path: str
    before_hash: str = ""
    after_hash: str = ""
    diff: str = ""
    reason: str = ""
    id: str = field(default_factory=lambda: _id("fc"))


@dataclass
class UserMemory:
    """A durable fact about the user, remembered ACROSS conversations.
    Authenticated-principal scoped and fully visible/deletable — never hidden."""
    text: str
    owner_id: str = ""
    kind: str = "fact"                     # fact | preference | project | identity
    source_conv: str = ""
    id: str = field(default_factory=lambda: _id("mem"))
    created_at: str = field(default_factory=_now)


class WorkspaceStore:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.conv_dir = self.base / "conversations"
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        self.mem_dir = self.base / "memories"
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        self.projects_path = self.base / "projects.jsonl"
        self._lock = threading.RLock()

    @staticmethod
    def _require_owner(owner_id: str) -> str:
        owner_id = (owner_id or "").strip()
        if not owner_id:
            raise ValueError("authenticated owner_id is required")
        return owner_id

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    # ── cross-session user memory (owner-scoped, transparent) ─────────────────
    def _mem_path(self, owner_id: str) -> Path:
        owner_id = self._require_owner(owner_id)
        safe = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()
        return self.mem_dir / f"{safe}.jsonl"

    def list_memories(self, owner_id: str) -> List[Dict[str, Any]]:
        p = self._mem_path(owner_id)
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out

    def _write_memories(self, owner_id: str, mems: List[Dict[str, Any]]) -> None:
        self._atomic_write(
            self._mem_path(owner_id),
            "\n".join(json.dumps(m, ensure_ascii=False) for m in mems) + ("\n" if mems else ""),
        )

    def add_memory(self, owner_id: str, text: str, *, kind: str = "fact",
                   source_conv: str = "", cap: int = 60) -> Optional[Dict[str, Any]]:
        text = (text or "").strip()[:400]
        if not text:
            return None
        owner_id = self._require_owner(owner_id)
        with self._lock:
            mems = self.list_memories(owner_id)
            norm = " ".join(text.lower().split())
            for m in mems:                   # dedup: skip near-duplicates / containment
                ex = " ".join((m.get("text") or "").lower().split())
                if ex == norm or (len(norm) > 12 and (norm in ex or ex in norm)):
                    return None
            entry = asdict(UserMemory(text=text, owner_id=owner_id, kind=kind,
                                      source_conv=source_conv))
            mems.append(entry)
            if len(mems) > cap:              # bounded: drop the oldest
                mems = mems[-cap:]
            self._write_memories(owner_id, mems)
            return entry

    def delete_memory(self, owner_id: str, mem_id: str) -> bool:
        with self._lock:
            mems = self.list_memories(owner_id)
            kept = [m for m in mems if m.get("id") != mem_id]
            if len(kept) == len(mems):
                return False
            self._write_memories(owner_id, kept)
            return True

    def clear_memories(self, owner_id: str) -> int:
        with self._lock:
            n = len(self.list_memories(owner_id))
            self._write_memories(owner_id, [])
            return n

    # ── conversations ────────────────────────────────────────────────────────
    def _conv_path(self, conv_id: str) -> Path:
        safe = "".join(c for c in conv_id if c.isalnum() or c in "-_")[:64]
        return self.conv_dir / f"{safe}.json"

    def create_conversation(self, owner_id: str, title: str = "New conversation",
                            project_id: str = "", mode: str = "chat") -> Dict[str, Any]:
        owner_id = self._require_owner(owner_id)
        conv = Conversation(title=title or "New conversation", project_id=project_id,
                            mode=mode, owner_id=owner_id)
        self._save_conv(conv)
        return asdict(conv)

    def _save_conv(self, conv: Conversation) -> None:
        conv.updated_at = _now()
        self._atomic_write(self._conv_path(conv.id), json.dumps(asdict(conv), ensure_ascii=False, indent=2))

    def _load_conv(self, conv_id: str) -> Optional[Conversation]:
        p = self._conv_path(conv_id)
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        if "owner_id" not in d and "owner" in d:
            d["owner_id"] = d.pop("owner")
        return Conversation(**{k: v for k, v in d.items() if k in Conversation.__dataclass_fields__})

    def get_conversation(self, owner_id: str, conv_id: str) -> Optional[Dict[str, Any]]:
        owner_id = self._require_owner(owner_id)
        c = self._load_conv(conv_id)
        return asdict(c) if c and c.owner_id == owner_id else None

    def list_conversations(self, owner_id: str, *, include_archived: bool = False,
                           project_id: str = "", query: str = "",
                           limit: int = 200) -> List[Dict[str, Any]]:
        owner_id = self._require_owner(owner_id)
        out: List[Dict[str, Any]] = []
        for p in self.conv_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            stored_owner = d.get("owner_id", d.get("owner", ""))
            if stored_owner != owner_id:
                continue
            if d.get("archived") and not include_archived:
                continue
            if project_id and d.get("project_id") != project_id:
                continue
            if query and query.lower() not in (d.get("title", "") + " " +
                    " ".join(m.get("content", "") for m in d.get("messages", []))).lower():
                continue
            out.append({k: d.get(k) for k in (
                "id", "title", "project_id", "created_at", "updated_at", "archived",
                "last_model_used", "last_verdict", "mode")} | {"turns": len(d.get("messages", []))})
        out.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
        return out[:limit]

    def rename_conversation(self, owner_id: str, conv_id: str, title: str) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        if c and c.owner_id != self._require_owner(owner_id):
            c = None
        if not c:
            return None
        c.title = title[:200]
        self._save_conv(c)
        return asdict(c)

    def set_archived(self, owner_id: str, conv_id: str, archived: bool) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        if c and c.owner_id != self._require_owner(owner_id):
            c = None
        if not c:
            return None
        c.archived = archived
        self._save_conv(c)
        return asdict(c)

    def set_mode(self, owner_id: str, conv_id: str, mode: str) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        if c and c.owner_id != self._require_owner(owner_id):
            c = None
        if not c:
            return None
        c.mode = (mode or "chat")[:40]
        self._save_conv(c)
        return asdict(c)

    def append_message(self, owner_id: str, conv_id: str, role: str, content: str, *,
                       model_used: str = "", receipt_id: str = "",
                       verdict: str = "", meta: Optional[Dict[str, Any]] = None
                       ) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        if c and c.owner_id != self._require_owner(owner_id):
            c = None
        if not c:
            return None
        msg = Message(role=role, content=content, conversation_id=conv_id,
                      model_used=model_used, receipt_id=receipt_id, meta=meta or {})
        c.messages.append(asdict(msg))
        if model_used:
            c.last_model_used = model_used
        if verdict:
            c.last_verdict = verdict
        # Auto-title from the first user message.
        if c.title == "New conversation" and role == "user" and content.strip():
            c.title = content.strip()[:60]
        self._save_conv(c)
        return asdict(msg)

    # ── projects ─────────────────────────────────────────────────────────────
    def create_project(self, owner_id: str, name: str, **kw) -> Dict[str, Any]:
        owner_id = self._require_owner(owner_id)
        proj = Project(name=name, owner_id=owner_id, **{k: v for k, v in kw.items()
                                     if k in Project.__dataclass_fields__})
        with self._lock:
            rows = self._load_projects()
            rows.append(asdict(proj))
            self._atomic_write(
                self.projects_path,
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            )
        return asdict(proj)

    def _load_projects(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            for line in self.projects_path.read_text().splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        except FileNotFoundError:
            pass
        return rows

    def list_projects(self, owner_id: str) -> List[Dict[str, Any]]:
        owner_id = self._require_owner(owner_id)
        return [row for row in self._load_projects()
                if row.get("owner_id", row.get("owner", "")) == owner_id]

    def stats(self, owner_id: str) -> Dict[str, Any]:
        convs = self.list_conversations(owner_id, include_archived=True)
        return {"conversations": len(convs),
                "active": sum(1 for c in convs if not c.get("archived")),
                "projects": len(self.list_projects(owner_id)),
                "turns": sum(c.get("turns", 0) for c in convs)}
