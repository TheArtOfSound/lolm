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
    owner: str = ""                        # per-browser key (localStorage) — keeps each
                                           # visitor's workspace separate without accounts
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


class WorkspaceStore:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.conv_dir = self.base / "conversations"
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        self.projects_path = self.base / "projects.jsonl"

    # ── conversations ────────────────────────────────────────────────────────
    def _conv_path(self, conv_id: str) -> Path:
        safe = "".join(c for c in conv_id if c.isalnum() or c in "-_")[:64]
        return self.conv_dir / f"{safe}.json"

    def create_conversation(self, title: str = "New conversation", project_id: str = "",
                            mode: str = "chat", owner: str = "") -> Dict[str, Any]:
        conv = Conversation(title=title or "New conversation", project_id=project_id,
                            mode=mode, owner=owner)
        self._save_conv(conv)
        return asdict(conv)

    def _save_conv(self, conv: Conversation) -> None:
        conv.updated_at = _now()
        self._conv_path(conv.id).write_text(json.dumps(asdict(conv), ensure_ascii=False, indent=2))

    def _load_conv(self, conv_id: str) -> Optional[Conversation]:
        p = self._conv_path(conv_id)
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return Conversation(**{k: v for k, v in d.items() if k in Conversation.__dataclass_fields__})

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        return asdict(c) if c else None

    def list_conversations(self, *, owner: str = "", include_archived: bool = False,
                           project_id: str = "", query: str = "",
                           limit: int = 200) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for p in self.conv_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            if owner and d.get("owner", "") != owner:
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

    def rename_conversation(self, conv_id: str, title: str) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        if not c:
            return None
        c.title = title[:200]
        self._save_conv(c)
        return asdict(c)

    def set_archived(self, conv_id: str, archived: bool) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        if not c:
            return None
        c.archived = archived
        self._save_conv(c)
        return asdict(c)

    def set_mode(self, conv_id: str, mode: str) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
        if not c:
            return None
        c.mode = (mode or "chat")[:40]
        self._save_conv(c)
        return asdict(c)

    def append_message(self, conv_id: str, role: str, content: str, *,
                       model_used: str = "", receipt_id: str = "",
                       verdict: str = "", meta: Optional[Dict[str, Any]] = None
                       ) -> Optional[Dict[str, Any]]:
        c = self._load_conv(conv_id)
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
    def create_project(self, name: str, **kw) -> Dict[str, Any]:
        proj = Project(name=name, **{k: v for k, v in kw.items()
                                     if k in Project.__dataclass_fields__})
        with self.projects_path.open("a") as f:
            f.write(json.dumps(asdict(proj), ensure_ascii=False) + "\n")
        return asdict(proj)

    def list_projects(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            for line in self.projects_path.read_text().splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        except FileNotFoundError:
            pass
        return rows

    def stats(self) -> Dict[str, Any]:
        convs = self.list_conversations(include_archived=True)
        return {"conversations": len(convs),
                "active": sum(1 for c in convs if not c.get("archived")),
                "projects": len(self.list_projects()),
                "turns": sum(c.get("turns", 0) for c in convs)}
