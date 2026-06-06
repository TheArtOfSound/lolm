"""Self-tick engine for LOLM-NFET.

A self-tick reads local memory, goals, summaries, and journal, then creates a
new inbox item and saves a learning event. It is local and runs only when called
by the user interface or script.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel


class SelfTickRequest(BaseModel):
    directive: str = ""
    max_new_tokens: int = 96
    temperature: float = 0.35
    top_p: float = 0.9
    use_graft: bool = True


class SelfTickEngine:
    def __init__(self, data_dir: Path, memory: Any, ChatMessage: Any, ChatRequest: Any, generation_loop: Callable[[Any], Any], append_event: Callable[[Dict[str, Any]], None]) -> None:
        self.data_dir = data_dir
        self.memory = memory
        self.ChatMessage = ChatMessage
        self.ChatRequest = ChatRequest
        self.generation_loop = generation_loop
        self.append_event = append_event
        self.inbox_path = data_dir / "self_tick_inbox.jsonl"
        self.last_result: Optional[Dict[str, Any]] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "identity": self.memory.read_identity()[-2000:],
            "goals": [g for g in self.memory.get_goals() if g.get("status", "active") == "active"][:8],
            "notes": self.memory.recent_notes(limit=10),
            "summaries": self.memory.recent_summaries(limit=5),
            "journal": self.memory.read_journal(max_chars=2500),
        }

    def choose_directive(self, explicit: str, snap: Dict[str, Any]) -> str:
        if explicit.strip():
            return explicit.strip()
        goals = snap.get("goals") or []
        if goals:
            top = sorted(goals, key=lambda g: int(g.get("priority", 3)), reverse=True)[0]
            return f"Advance active goal: {top.get('title', '')}. Identify the next useful action and what should be remembered."
        return "Review memory and journal. Decide one useful next action for this workspace and explain why it matters."

    def collect(self, req: Any) -> Dict[str, Any]:
        final: Optional[Dict[str, Any]] = None
        text = ""
        tokens = 0
        started = time.perf_counter()
        for event in self.generation_loop(req):
            kind = event.get("event")
            data = event.get("data", {})
            if kind == "error":
                raise RuntimeError(data.get("error", "generation failed"))
            if kind == "token":
                text += data.get("token", "")
                tokens += 1
            if kind == "done":
                final = data
        elapsed = max(time.perf_counter() - started, 1e-9)
        if final is None:
            final = {"response": text, "tokens": tokens}
        final["seconds"] = elapsed
        final["tok_per_sec"] = tokens / elapsed
        return final

    def append_jsonl(self, path: Path, row: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def tick(self, req: SelfTickRequest) -> Dict[str, Any]:
        run_id = uuid.uuid4().hex[:10]
        now = time.time()
        snap = self.snapshot()
        directive = self.choose_directive(req.directive, snap)
        system = "You are LOLM-NFET Self Tick. Review local state and create a useful inbox item. Be concrete and do not claim actions not performed."
        user = f"Directive:\n{directive}\n\nLocal state:\n{json.dumps(snap, indent=2, ensure_ascii=False)[:8000]}\n\nReturn five sections: noticed, why it matters, next action, remember, inbox message."
        chat_req = self.ChatRequest(
            messages=[self.ChatMessage(role="system", content=system), self.ChatMessage(role="user", content=user)],
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
            use_graft=req.use_graft,
            ablation_mode="full",
        )
        result = self.collect(chat_req)
        text = (result.get("response") or "").strip() or "Self tick produced no text."
        self.memory.append_journal(f"## Self Tick {run_id}\n\nDirective: {directive}\n\n{text}")
        self.memory.add_summary(text[:1200], span="self_tick")
        self.memory.append_note(f"Self tick {run_id}: {directive}", tag="self_tick", importance=5)
        inbox = {"id": run_id, "ts": now, "directive": directive, "summary": text[:1800], "result_id": result.get("id"), "tokens": result.get("tokens"), "tok_per_sec": result.get("tok_per_sec")}
        self.append_jsonl(self.inbox_path, inbox)
        event = {"type": "self_tick", "timestamp": now, "id": run_id, "directive": directive, "inbox": inbox}
        self.append_event(event)
        self.last_result = {"ok": True, "snapshot": snap, "inbox": inbox, "event": event}
        return self.last_result

    def status(self) -> Dict[str, Any]:
        return {"last_result": self.last_result}


def register_self_tick_routes(app: Any, engine: SelfTickEngine) -> None:
    @app.get("/api/self/status")
    def self_status():
        return engine.status()

    @app.post("/api/self/tick")
    def self_tick(req: SelfTickRequest):
        return engine.tick(req)
