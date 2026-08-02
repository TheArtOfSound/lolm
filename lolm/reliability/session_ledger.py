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
        self.root.mkdir(parents=True, exist_ok=True)
        sid = (session_id or "").strip() or f"sess_{uuid.uuid4().hex[:12]}"
        self.pointers = SessionPointers(
            session_id=sid,
            owner=owner,
            conversation_id=conversation_id,
            updated_ts=time.time(),
        )
        self._path = self.root / f"{sid}.json"
        self.load()

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
        self.pointers.history.append({
            "kind": "code_run", "run_id": run_id, "task": task[:300],
            "status": status, "ts": time.time(),
        })
        self.pointers.history = self.pointers.history[-50:]
        self.save()

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
                return {
                    "action": "retry",
                    "run_id": rid,
                    "task": self.pointers.last_run_task,
                    "checkpoint_id": self.pointers.last_checkpoint_id,
                    "status": self.pointers.last_run_status,
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
            if rid and self.pointers.last_run_status == "terminated":
                return {
                    "action": "resume",
                    "run_id": rid,
                    "checkpoint_id": self.pointers.last_checkpoint_id,
                    "task": self.pointers.last_run_task,
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
