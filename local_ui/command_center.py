"""Command Center product layer for LOLM-NFET.

This turns the local workspace from a model-debug cockpit into a task runner:
Command -> Plan -> Actions -> Memory used -> Result -> Proof -> Saved learning.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel


class CommandRunRequest(BaseModel):
    command: str
    max_new_tokens: int = 96
    temperature: float = 0.35
    top_p: float = 0.9
    use_graft: bool = True
    ablation_mode: str = "full"


class CommandMemoryHit(BaseModel):
    kind: str
    text: str
    meta: Dict[str, Any] = {}


def _collect_generation(req: Any, generation_loop: Callable[[Any], Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    final: Optional[Dict[str, Any]] = None
    streamed = ""
    tokens = 0
    for event in generation_loop(req):
        name = event.get("event")
        data = event.get("data", {})
        if name == "error":
            raise RuntimeError(data.get("error", "generation failed"))
        if name == "token":
            streamed += data.get("token", "")
            tokens += 1
        if name == "done":
            final = data
    elapsed = max(time.perf_counter() - started, 1e-9)
    if final is None:
        final = {"response": streamed, "tokens": tokens}
    final["seconds"] = elapsed
    final["tok_per_sec"] = tokens / elapsed
    return final


def _memory_hits(memory: Any, command: str) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    identity = memory.read_identity().strip()
    if identity:
        hits.append({"kind": "identity", "text": identity[-1200:], "meta": {}})
    for goal in memory.get_goals()[:8]:
        if goal.get("status", "active") == "active":
            hits.append({"kind": "goal", "text": goal.get("title", ""), "meta": {"why": goal.get("why", ""), "priority": goal.get("priority")}})
    for note in memory.search_notes(command, limit=8):
        hits.append({"kind": "memory", "text": note.get("text", ""), "meta": {"tag": note.get("tag"), "importance": note.get("importance"), "ts": note.get("ts")}})
    return [h for h in hits if h.get("text")]


def _context_block(hits: List[Dict[str, Any]]) -> str:
    if not hits:
        return "No relevant local memory was found."
    rows = []
    for hit in hits[:12]:
        rows.append(f"[{hit['kind']}] {hit['text']}")
    return "\n".join(rows)


def _messages(ChatMessage: Any, command: str, hits: List[Dict[str, Any]]) -> List[Any]:
    system = (
        "You are LOLM Command Center, a local operator workspace. "
        "Do not act like a generic chatbot. Produce a useful task result. "
        "Use the provided local memory only when relevant. "
        "Return a concise but complete answer with concrete next actions."
    )
    user = f"""COMMAND:
{command}

LOCAL MEMORY / GOALS / IDENTITY:
{_context_block(hits)}

RESPONSE FORMAT:
1. Result
2. Actions taken or simulated
3. Memory used
4. Proof of difference
5. Saved learning"""
    return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]


def _base_messages(ChatMessage: Any, command: str) -> List[Any]:
    return [
        ChatMessage(role="system", content="You are a normal local chatbot. Answer the user directly."),
        ChatMessage(role="user", content=command),
    ]


def _proof(base: Dict[str, Any], command_result: Dict[str, Any], hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    base_text = (base.get("response") or "").strip()
    result_text = (command_result.get("response") or "").strip()
    base_words = set(base_text.lower().split())
    result_words = set(result_text.lower().split())
    similarity = len(base_words & result_words) / max(len(base_words | result_words), 1)
    summary = command_result.get("summary", {}) or {}
    memory_terms = [h["text"].split()[0].lower().strip(" .,:;!?()[]{}") for h in hits if h.get("text")]
    memory_terms = [t for t in memory_terms if len(t) > 3][:12]
    memory_term_hits = sum(1 for t in memory_terms if t in result_text.lower())
    changed = base_text != result_text
    used_memory = bool(hits) and ("memory" in result_text.lower() or memory_term_hits > 0)
    if changed and used_memory:
        verdict = "command_center_difference_visible"
        plain = "The Command Center result differs from the base answer and shows visible use of local context."
    elif changed:
        verdict = "changed_but_memory_not_obvious"
        plain = "The result differs from the base answer, but memory/tool consequence is not obvious enough yet."
    else:
        verdict = "no_visible_difference"
        plain = "The Command Center did not visibly improve over base mode."
    return {
        "verdict": verdict,
        "plain": plain,
        "changed_text": changed,
        "word_similarity": round(similarity, 3),
        "memory_hits_available": len(hits),
        "memory_term_hits": memory_term_hits,
        "avg_gate": summary.get("avg_gate"),
        "avg_latent_share": summary.get("avg_latent_share"),
        "last_control": summary.get("last_control"),
        "base_tok_per_sec": round(base.get("tok_per_sec", 0), 3),
        "command_tok_per_sec": round(command_result.get("tok_per_sec", 0), 3),
    }


def register_command_routes(
    app: Any,
    ChatMessage: Any,
    ChatRequest: Any,
    generation_loop: Callable[[Any], Any],
    memory: Any,
    append_improvement_event: Callable[[Dict[str, Any]], None],
) -> None:
    @app.post("/api/command/run")
    def command_run(req: CommandRunRequest):
        command = req.command.strip()
        if not command:
            return {"error": "empty command"}

        hits = _memory_hits(memory, command)
        plan = [
            "Read the user command.",
            "Retrieve relevant local memory, identity, and active goals.",
            "Generate a Command Center result with LOLM/NFET enabled.",
            "Run a base-mode comparison.",
            "Save the run as local learning data.",
        ]
        actions = [
            {"kind": "memory_search", "status": "done", "count": len(hits)},
            {"kind": "lolm_generation", "status": "done", "graft": req.use_graft},
            {"kind": "base_comparison", "status": "done", "graft": False},
            {"kind": "learning_log", "status": "done"},
        ]

        command_messages = _messages(ChatMessage, command, hits)
        command_result = _collect_generation(
            ChatRequest(
                messages=command_messages,
                max_new_tokens=req.max_new_tokens,
                temperature=req.temperature,
                top_p=req.top_p,
                use_graft=req.use_graft,
                ablation_mode=req.ablation_mode,
            ),
            generation_loop,
        )
        base_result = _collect_generation(
            ChatRequest(
                messages=_base_messages(ChatMessage, command),
                max_new_tokens=min(req.max_new_tokens, 64),
                temperature=req.temperature,
                top_p=req.top_p,
                use_graft=False,
                ablation_mode=req.ablation_mode,
            ),
            generation_loop,
        )
        proof = _proof(base_result, command_result, hits)
        learning = {
            "type": "command_center_run",
            "timestamp": time.time(),
            "command": command,
            "plan": plan,
            "actions": actions,
            "memory_used": hits,
            "result_id": command_result.get("id"),
            "base_id": base_result.get("id"),
            "proof": proof,
        }
        append_improvement_event(learning)
        memory.append_journal(f"## Command Center Run\n\nCommand: {command}\n\nVerdict: {proof['verdict']}\n\nSaved learning event: command_center_run")
        return {
            "command": command,
            "plan": plan,
            "actions": actions,
            "memory_used": hits,
            "result": command_result,
            "base": base_result,
            "proof": proof,
            "saved_learning": learning,
        }
