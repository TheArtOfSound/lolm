# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Session Intent Ledger (SIL).

Persist cross-command conversational and task referents:
last ask, last code run, last failed run, open question, option set,
selected option, artifact IDs, unresolved pronouns.

Commands: lolm last, lolm retry, lolm resume, lolm inspect.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Follow-ups that need a referent
_RETRY_CUES = re.compile(
    r"^\s*(try\s+again|retry|again|once\s+more|same\s+as\s+before|redo|re-?run)\s*[.!]?\s*$",
    re.I,
)
_CONTINUE_CUES = re.compile(
    r"^\s*(continue|go\s+on|keep\s+going|resume|pick\s+up)\s*[.!]?\s*$",
    re.I,
)
_ORDINAL = re.compile(r"^\s*(\d+|one|two|three|first|second|third)\s*[.!]?\s*$", re.I)
_PRONOUN = re.compile(
    r"^\s*(that|this|it|those|the\s+same|fix\s+that|do\s+that)\s*[.!]?\s*$",
    re.I,
)
_SMALLTALK = re.compile(
    r"^\s*(not\s+bad|good|fine|ok|okay|great|thanks|thank\s+you|hi|hello|hey)\b",
    re.I,
)

_ORDINAL_MAP = {
    "1": 0, "one": 0, "first": 0,
    "2": 1, "two": 1, "second": 1,
    "3": 2, "three": 2, "third": 2,
}


def default_ledger_path() -> Path:
    base = os.environ.get("LOLM_SESSION_DIR") or os.path.expanduser("~/.lolm/sessions")
    return Path(base)


def sanitize_session_id(raw: str) -> str:
    """Opaque filesystem-safe session id — no path traversal.

    Accepts only [A-Za-z0-9_-]; anything else is hashed to sess_<sha16>.
    """
    s = (raw or "").strip()
    if not s:
        return f"sess_{uuid.uuid4().hex[:12]}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", s) and ".." not in s and "/" not in s and "\\" not in s:
        # Still reject path-like stems
        if s in (".", "..") or s.startswith("."):
            pass
        else:
            return s
    import hashlib
    return "sess_" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@dataclass
class SessionPointers:
    session_id: str
    last_ask: str = ""
    last_ask_id: str = ""
    last_code_run_id: str = ""
    last_failed_run_id: str = ""
    last_run_task: str = ""
    last_run_status: str = ""  # shipped | broken | terminated | stuck
    open_question: str = ""
    option_set: List[str] = field(default_factory=list)
    selected_option: str = ""
    artifact_ids: List[str] = field(default_factory=list)
    unresolved_pronouns: List[str] = field(default_factory=list)
    last_checkpoint_id: str = ""
    conversation_id: str = ""
    owner: str = ""
    updated_ts: float = 0.0
    history: List[Dict[str, Any]] = field(default_factory=list)
    # Genuine resume transport (not just task text)
    resume_token: str = ""
    workspace_snapshot: Dict[str, str] = field(default_factory=dict)  # path -> content
    reliability_snapshot: Dict[str, Any] = field(default_factory=dict)
    failure_ledger: Dict[str, Any] = field(default_factory=dict)
    contract_snapshot: Dict[str, Any] = field(default_factory=dict)
    checkpoint_payload: Dict[str, Any] = field(default_factory=dict)
    event_cursor: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SessionPointers":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


class SessionIntentLedger:
    """Durable session referents across process boundaries."""

    def __init__(
        self,
        session_id: str = "",
        *,
        root: Optional[Path] = None,
        owner: str = "",
        conversation_id: str = "",
    ) -> None:
        self.root = Path(root) if root else default_ledger_path()
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        sid = sanitize_session_id(session_id)
        self.pointers = SessionPointers(
            session_id=sid,
            owner=owner,
            conversation_id=conversation_id,
            updated_ts=time.time(),
        )
        self._path = self._safe_path(sid)
        self.load()

    def _safe_path(self, sid: str) -> Path:
        """Ensure ledger file stays under root (no traversal)."""
        sid = sanitize_session_id(sid)
        path = (self.root / f"{sid}.json").resolve()
        if self.root not in path.parents and path.parent != self.root:
            # Should never happen after sanitize; force hash name
            sid = sanitize_session_id("unsafe:" + sid)
            path = (self.root / f"{sid}.json").resolve()
        if self.root not in path.parents and path.parent != self.root:
            raise ValueError("session path escapes ledger root")
        return path

    @property
    def session_id(self) -> str:
        return self.pointers.session_id

    def load(self) -> bool:
        if not self._path.exists():
            return False
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self.pointers = SessionPointers.from_dict(data)
            return True
        except Exception:
            return False

    def save(self) -> None:
        self.pointers.updated_ts = time.time()
        self._path.write_text(
            json.dumps(self.pointers.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def record_ask(self, text: str, ask_id: str = "") -> None:
        self.pointers.last_ask = text
        self.pointers.last_ask_id = ask_id or f"ask_{uuid.uuid4().hex[:10]}"
        self.pointers.history.append({
            "kind": "ask", "text": text[:500], "id": self.pointers.last_ask_id,
            "ts": time.time(),
        })
        self.pointers.history = self.pointers.history[-50:]
        self.save()

    def record_code_run(
        self,
        *,
        run_id: str,
        task: str,
        status: str,
        artifact_ids: Optional[Sequence[str]] = None,
        checkpoint_id: str = "",
        failed: bool = False,
        workspace_snapshot: Optional[Dict[str, str]] = None,
        reliability_snapshot: Optional[Dict[str, Any]] = None,
        failure_ledger: Optional[Dict[str, Any]] = None,
        contract_snapshot: Optional[Dict[str, Any]] = None,
        checkpoint_payload: Optional[Dict[str, Any]] = None,
        event_cursor: int = 0,
        resume_token: str = "",
    ) -> None:
        self.pointers.last_code_run_id = run_id
        self.pointers.last_run_task = task
        self.pointers.last_run_status = status
        if failed or status in ("broken", "terminated", "stuck"):
            self.pointers.last_failed_run_id = run_id
        if artifact_ids:
            for a in artifact_ids:
                if a not in self.pointers.artifact_ids:
                    self.pointers.artifact_ids.append(a)
            self.pointers.artifact_ids = self.pointers.artifact_ids[-20:]
        if checkpoint_id:
            self.pointers.last_checkpoint_id = checkpoint_id
        # Resume transport package
        if workspace_snapshot is not None:
            # Cap size to keep ledger portable
            capped: Dict[str, str] = {}
            total = 0
            for p, c in list(workspace_snapshot.items())[:40]:
                body = c if isinstance(c, str) else str(c)
                if total + len(body) > 1_500_000:
                    break
                capped[p] = body
                total += len(body)
            self.pointers.workspace_snapshot = capped
        if reliability_snapshot is not None:
            self.pointers.reliability_snapshot = dict(reliability_snapshot)
        if failure_ledger is not None:
            self.pointers.failure_ledger = dict(failure_ledger)
        if contract_snapshot is not None:
            self.pointers.contract_snapshot = dict(contract_snapshot)
        if checkpoint_payload is not None:
            self.pointers.checkpoint_payload = dict(checkpoint_payload)
        self.pointers.event_cursor = int(event_cursor or 0)
        if resume_token:
            self.pointers.resume_token = resume_token
        elif run_id and checkpoint_id:
            self.pointers.resume_token = f"resume:{run_id}:{checkpoint_id}"
        self.pointers.history.append({
            "kind": "code_run", "run_id": run_id, "task": task[:300],
            "status": status, "ts": time.time(),
            "resume_token": self.pointers.resume_token,
            "checkpoint_id": checkpoint_id,
            "has_workspace": bool(self.pointers.workspace_snapshot),
        })
        self.pointers.history = self.pointers.history[-50:]
        self.save()

    def resume_package(self) -> Optional[Dict[str, Any]]:
        """Full resume transport — empty if no checkpoint/workspace bound."""
        p = self.pointers
        if not (p.resume_token or p.last_checkpoint_id or p.workspace_snapshot):
            return None
        return {
            "resume_token": p.resume_token,
            "run_id": p.last_code_run_id,
            "task": p.last_run_task,
            "status": p.last_run_status,
            "checkpoint_id": p.last_checkpoint_id,
            "workspace_snapshot": dict(p.workspace_snapshot),
            "reliability_snapshot": dict(p.reliability_snapshot),
            "failure_ledger": dict(p.failure_ledger),
            "contract_snapshot": dict(p.contract_snapshot),
            "checkpoint_payload": dict(p.checkpoint_payload),
            "event_cursor": p.event_cursor,
            "session_id": p.session_id,
            "conversation_id": p.conversation_id,
        }

    def record_options(self, options: Sequence[str], question: str = "") -> None:
        self.pointers.option_set = list(options)
        self.pointers.open_question = question
        self.pointers.selected_option = ""
        self.save()

    def select_option(self, index: int) -> Optional[str]:
        if 0 <= index < len(self.pointers.option_set):
            self.pointers.selected_option = self.pointers.option_set[index]
            self.save()
            return self.pointers.selected_option
        return None

    def resolve_followup(self, text: str) -> Dict[str, Any]:
        """Resolve bare follow-ups against durable referents.

        Returns action: retry | resume | select_option | continue_ask | clarify | passthrough
        """
        t = (text or "").strip()
        if not t:
            return {"action": "clarify", "reason": "empty input", "prompt": "What should I do?"}

        if _RETRY_CUES.match(t):
            rid = self.pointers.last_failed_run_id or self.pointers.last_code_run_id
            if rid:
                pkg = self.resume_package()
                return {
                    "action": "retry",
                    "run_id": rid,
                    "task": self.pointers.last_run_task,
                    "checkpoint_id": self.pointers.last_checkpoint_id,
                    "status": self.pointers.last_run_status,
                    "resume_token": self.pointers.resume_token,
                    "resume_package": pkg,
                    "confirm_prompt": (
                        f"Retry run {rid} ({self.pointers.last_run_status}) "
                        f"task={self.pointers.last_run_task[:80]!r}? "
                        "Use `lolm retry --yes` to confirm."
                    ),
                }
            if self.pointers.last_ask:
                return {
                    "action": "retry_ask",
                    "ask": self.pointers.last_ask,
                    "ask_id": self.pointers.last_ask_id,
                }
            return {
                "action": "clarify",
                "reason": "no resolvable run or ask referent",
                "prompt": "Nothing to retry. Provide a task or ask first.",
            }

        if _CONTINUE_CUES.match(t):
            rid = self.pointers.last_code_run_id
            pkg = self.resume_package()
            if rid and (
                self.pointers.last_run_status == "terminated"
                or (pkg and pkg.get("workspace_snapshot"))
            ):
                return {
                    "action": "resume",
                    "run_id": rid,
                    "checkpoint_id": self.pointers.last_checkpoint_id,
                    "task": self.pointers.last_run_task,
                    "resume_token": self.pointers.resume_token,
                    "resume_package": pkg,
                }
            if self.pointers.open_question:
                return {
                    "action": "continue_ask",
                    "question": self.pointers.open_question,
                    "last_ask": self.pointers.last_ask,
                }
            return {
                "action": "clarify",
                "reason": "no resumable run",
                "prompt": "No interrupted run to resume. Start a new code task or ask.",
            }

        if _ORDINAL.match(t) and self.pointers.option_set:
            key = t.strip().lower().rstrip(".!")
            idx = _ORDINAL_MAP.get(key)
            if idx is None and key.isdigit():
                idx = int(key) - 1
            if idx is not None:
                opt = self.select_option(idx)
                if opt is not None:
                    return {"action": "select_option", "index": idx, "option": opt}
            return {
                "action": "clarify",
                "reason": "ordinal out of range",
                "prompt": (
                    f"Options are 1..{len(self.pointers.option_set)}: "
                    + "; ".join(f"{i+1}. {o}" for i, o in enumerate(self.pointers.option_set[:5]))
                ),
            }

        if _PRONOUN.match(t):
            if self.pointers.last_run_task:
                return {
                    "action": "retry",
                    "run_id": self.pointers.last_code_run_id,
                    "task": self.pointers.last_run_task,
                    "referent": "last_code_run",
                }
            if self.pointers.last_ask:
                return {
                    "action": "retry_ask",
                    "ask": self.pointers.last_ask,
                    "referent": "last_ask",
                }
            return {
                "action": "clarify",
                "reason": "unresolved pronoun",
                "prompt": "What does 'that' refer to? No prior task is bound in this session.",
            }

        if _SMALLTALK.match(t) and self.pointers.open_question:
            return {
                "action": "continue_ask",
                "question": self.pointers.open_question,
                "user_reply": t,
                "last_ask": self.pointers.last_ask,
                "note": "bound smalltalk to open conversational question",
            }

        return {"action": "passthrough", "text": t}

    def last_summary(self) -> Dict[str, Any]:
        p = self.pointers
        return {
            "session_id": p.session_id,
            "last_ask": p.last_ask[:200],
            "last_code_run_id": p.last_code_run_id,
            "last_failed_run_id": p.last_failed_run_id,
            "last_run_task": p.last_run_task[:200],
            "last_run_status": p.last_run_status,
            "open_question": p.open_question[:200],
            "option_set": p.option_set[:10],
            "selected_option": p.selected_option,
            "artifact_ids": p.artifact_ids[-5:],
            "last_checkpoint_id": p.last_checkpoint_id,
            "updated_ts": p.updated_ts,
        }

    @classmethod
    def latest(cls, root: Optional[Path] = None) -> Optional["SessionIntentLedger"]:
        base = Path(root) if root else default_ledger_path()
        if not base.exists():
            return None
        files = sorted(base.glob("sess_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            # also accept any *.json
            files = sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        sid = files[0].stem
        return cls(session_id=sid, root=base)
