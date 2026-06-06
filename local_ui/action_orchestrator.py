"""Action orchestrator for LOLM-NFET Command Center.

This is the bridge between telemetry/control labels and actual behavior:
- retrieve relevant local memory/goals/identity
- optionally search/fetch public web evidence
- generate multiple candidate answers
- verify/criticize candidates
- finalize a best answer
- save a learning receipt

It intentionally avoids arbitrary shell execution. Code/file mutation should be added
as explicit scoped tools, not as hidden model behavior.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel

from local_ui.internet_tools import fetch_url, web_search


class AgentRunRequest(BaseModel):
    command: str
    max_new_tokens: int = 160
    temperature: float = 0.25
    top_p: float = 0.9
    use_graft: bool = True
    ablation_mode: str = "full"
    allow_web: bool = False
    web_limit: int = 4


@dataclass
class GenerationResult:
    response: str
    raw: Dict[str, Any]


class ActionOrchestrator:
    def __init__(
        self,
        memory: Any,
        ChatMessage: Any,
        ChatRequest: Any,
        generation_loop: Callable[[Any], Any],
        append_event: Callable[[Dict[str, Any]], None],
    ) -> None:
        self.memory = memory
        self.ChatMessage = ChatMessage
        self.ChatRequest = ChatRequest
        self.generation_loop = generation_loop
        self.append_event = append_event

    def run(self, req: AgentRunRequest) -> Dict[str, Any]:
        command = req.command.strip()
        if not command:
            return {"error": "empty command"}

        started = time.time()
        plan = self._plan(command, req)
        memory_hits = self._retrieve_memory(command)
        web_evidence = self._maybe_web(command, req)
        base = self._generate_base(command, req)
        candidate_a = self._generate_candidate(command, req, memory_hits, web_evidence, style="direct operator answer")
        candidate_b = self._generate_candidate(command, req, memory_hits, web_evidence, style="critical revised answer")
        critique = self._verify(command, req, memory_hits, web_evidence, candidate_a, candidate_b)
        final = self._finalize(command, req, memory_hits, web_evidence, candidate_a, candidate_b, critique)
        proof = self._proof(command, base.raw, final.raw, memory_hits, web_evidence, critique)

        actions = [
            {"kind": "memory_retrieve", "status": "done", "count": len(memory_hits)},
            {"kind": "web_research", "status": "done" if web_evidence else "skipped", "count": len(web_evidence), "allow_web": req.allow_web},
            {"kind": "branch", "status": "done", "candidates": 2},
            {"kind": "verify", "status": "done"},
            {"kind": "finalize", "status": "done"},
            {"kind": "learning_log", "status": "done"},
        ]
        learning = {
            "type": "agent_orchestrator_run",
            "timestamp": started,
            "command": command,
            "plan": plan,
            "actions": actions,
            "memory_used": memory_hits,
            "web_evidence": web_evidence,
            "candidate_a_id": candidate_a.raw.get("id"),
            "candidate_b_id": candidate_b.raw.get("id"),
            "base_id": base.raw.get("id"),
            "final_id": final.raw.get("id"),
            "proof": proof,
        }
        self.append_event(learning)
        self.memory.append_journal(
            f"## Agent Orchestrator Run\n\nCommand: {command}\n\nVerdict: {proof['verdict']}\n\nActions: {', '.join(a['kind'] for a in actions)}"
        )
        self.memory.add_summary(final.response[:1200], span="agent_orchestrator")
        return {
            "command": command,
            "plan": plan,
            "actions": actions,
            "memory_used": memory_hits,
            "web_evidence": web_evidence,
            "base": base.raw,
            "candidates": [candidate_a.raw, candidate_b.raw],
            "critique": critique.raw,
            "result": final.raw,
            "proof": proof,
            "saved_learning": learning,
        }

    def _collect(self, messages: List[Any], req: AgentRunRequest, *, use_graft: Optional[bool] = None, tokens: Optional[int] = None) -> GenerationResult:
        chat_req = self.ChatRequest(
            messages=messages,
            max_new_tokens=tokens or req.max_new_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
            use_graft=req.use_graft if use_graft is None else use_graft,
            ablation_mode=req.ablation_mode,
        )
        final: Optional[Dict[str, Any]] = None
        text = ""
        token_count = 0
        started = time.perf_counter()
        for event in self.generation_loop(chat_req):
            kind = event.get("event")
            data = event.get("data", {})
            if kind == "error":
                raise RuntimeError(data.get("error", "generation failed"))
            if kind == "token":
                text += data.get("token", "")
                token_count += 1
            if kind == "done":
                final = data
        elapsed = max(time.perf_counter() - started, 1e-9)
        if final is None:
            final = {"response": text, "tokens": token_count}
        final["seconds"] = elapsed
        final["tok_per_sec"] = token_count / elapsed
        return GenerationResult(response=(final.get("response") or text or "").strip(), raw=final)

    def _plan(self, command: str, req: AgentRunRequest) -> List[str]:
        rows = [
            "Retrieve relevant local memory, identity, goals, summaries, and journal context.",
            "Decide whether external evidence is needed; use web only when explicitly allowed.",
            "Generate two answer branches: direct operator answer and critical revised answer.",
            "Verify the branches against available memory and evidence.",
            "Finalize the strongest answer with a proof receipt and save learning.",
        ]
        if req.allow_web:
            rows.insert(1, "Search/fetch public web evidence where useful.")
        return rows

    def _retrieve_memory(self, command: str) -> List[Dict[str, Any]]:
        hits: List[Dict[str, Any]] = []
        identity = self.memory.read_identity().strip()
        if identity:
            hits.append({"kind": "identity", "text": identity[-1600:], "meta": {"source": "identity.md"}})
        goals = [g for g in self.memory.get_goals() if g.get("status", "active") == "active"]
        for goal in sorted(goals, key=lambda g: int(g.get("priority", 3)), reverse=True)[:8]:
            hits.append({"kind": "goal", "text": goal.get("title", ""), "meta": {"why": goal.get("why", ""), "priority": goal.get("priority")}})
        for note in self.memory.search_notes(command, limit=10):
            hits.append({"kind": "memory", "text": note.get("text", ""), "meta": {"tag": note.get("tag"), "importance": note.get("importance"), "ts": note.get("ts")}})
        journal = self.memory.read_journal(max_chars=1800).strip()
        if journal:
            hits.append({"kind": "journal", "text": journal, "meta": {"source": "journal.md"}})
        return [h for h in hits if h.get("text")][:16]

    def _needs_web(self, command: str) -> bool:
        lower = command.lower()
        triggers = ["search", "web", "internet", "latest", "current", "today", "research", "look up", "verify online", "source"]
        if any(t in lower for t in triggers):
            return True
        return bool(re.search(r"https?://", command))

    def _maybe_web(self, command: str, req: AgentRunRequest) -> List[Dict[str, Any]]:
        if not req.allow_web or not self._needs_web(command):
            return []
        evidence: List[Dict[str, Any]] = []
        urls = re.findall(r'https?://[^\s)\]}>"\']+', command)
        for url in urls[:2]:
            try:
                fetched = fetch_url(url)
                evidence.append({"kind": "fetch", "title": urlparse(fetched.get("url", url)).netloc, "url": fetched.get("url", url), "text": fetched.get("text", "")[:1800]})
            except Exception as exc:
                evidence.append({"kind": "fetch_error", "url": url, "error": str(exc)[:300]})
        if len(evidence) < req.web_limit:
            try:
                results = web_search(command, limit=req.web_limit)
                for item in results.get("results", [])[: req.web_limit - len(evidence)]:
                    evidence.append({"kind": "search", "title": item.get("title", ""), "url": item.get("url", ""), "text": item.get("snippet", ""), "source": item.get("source", results.get("provider"))})
            except Exception as exc:
                evidence.append({"kind": "search_error", "error": str(exc)[:300]})
        return evidence[: req.web_limit]

    def _block(self, label: str, rows: List[Dict[str, Any]], limit: int = 7000) -> str:
        if not rows:
            return f"{label}: none"
        out = [f"{label}:"]
        for row in rows:
            prefix = row.get("kind", "item")
            meta = row.get("meta") or {}
            url = row.get("url")
            text = row.get("text", "")
            extra = f" url={url}" if url else ""
            out.append(f"[{prefix}{extra}] {text} {json.dumps(meta, ensure_ascii=False) if meta else ''}".strip())
        return "\n".join(out)[:limit]

    def _generate_base(self, command: str, req: AgentRunRequest) -> GenerationResult:
        messages = [
            self.ChatMessage(role="system", content="You are a normal local chatbot. Answer the user directly."),
            self.ChatMessage(role="user", content=command),
        ]
        return self._collect(messages, req, use_graft=False, tokens=min(req.max_new_tokens, 96))

    def _generate_candidate(self, command: str, req: AgentRunRequest, memory_hits: List[Dict[str, Any]], web_evidence: List[Dict[str, Any]], *, style: str) -> GenerationResult:
        system = (
            "You are LOLM-NFET Action Orchestrator. Produce an answer that reflects actual available context. "
            "Do not pretend to have performed actions not listed in evidence. Be concrete, useful, and self-critical."
        )
        user = f"""COMMAND:\n{command}\n\nSTYLE:\n{style}\n\n{self._block('LOCAL MEMORY', memory_hits)}\n\n{self._block('WEB EVIDENCE', web_evidence)}\n\nWrite a candidate answer. Include exactly what evidence or memory you used. If evidence is weak, say so."""
        return self._collect([self.ChatMessage(role="system", content=system), self.ChatMessage(role="user", content=user)], req)

    def _verify(self, command: str, req: AgentRunRequest, memory_hits: List[Dict[str, Any]], web_evidence: List[Dict[str, Any]], a: GenerationResult, b: GenerationResult) -> GenerationResult:
        system = "You are a verifier. Criticize candidate answers against the command, memory, and evidence. Pick the stronger candidate and list concrete fixes."
        user = f"""COMMAND:\n{command}\n\n{self._block('LOCAL MEMORY', memory_hits)}\n\n{self._block('WEB EVIDENCE', web_evidence)}\n\nCANDIDATE A:\n{a.response}\n\nCANDIDATE B:\n{b.response}\n\nReturn: winner, problems, missing actions, fixes, final-answer instructions."""
        return self._collect([self.ChatMessage(role="system", content=system), self.ChatMessage(role="user", content=user)], req, tokens=min(req.max_new_tokens, 128))

    def _finalize(self, command: str, req: AgentRunRequest, memory_hits: List[Dict[str, Any]], web_evidence: List[Dict[str, Any]], a: GenerationResult, b: GenerationResult, critique: GenerationResult) -> GenerationResult:
        system = "You are LOLM-NFET finalizer. Produce the final answer. It must be better than base mode because it uses retrieved context, verification, and branch critique."
        user = f"""COMMAND:\n{command}\n\n{self._block('LOCAL MEMORY', memory_hits)}\n\n{self._block('WEB EVIDENCE', web_evidence)}\n\nCANDIDATE A:\n{a.response}\n\nCANDIDATE B:\n{b.response}\n\nVERIFIER CRITIQUE:\n{critique.response}\n\nWrite the final answer with sections: Result, What I used, What I verified, Limits, Next action."""
        return self._collect([self.ChatMessage(role="system", content=system), self.ChatMessage(role="user", content=user)], req)

    def _proof(self, command: str, base: Dict[str, Any], final: Dict[str, Any], memory_hits: List[Dict[str, Any]], web_evidence: List[Dict[str, Any]], critique: GenerationResult) -> Dict[str, Any]:
        base_text = (base.get("response") or "").strip()
        final_text = (final.get("response") or "").strip()
        base_words = set(base_text.lower().split())
        final_words = set(final_text.lower().split())
        similarity = len(base_words & final_words) / max(len(base_words | final_words), 1)
        used_memory = bool(memory_hits) and ("memory" in final_text.lower() or "goal" in final_text.lower() or "journal" in final_text.lower() or "context" in final_text.lower())
        used_web = bool(web_evidence) and ("web" in final_text.lower() or "evidence" in final_text.lower() or "source" in final_text.lower())
        used_verify = bool(critique.response) and ("verified" in final_text.lower() or "limits" in final_text.lower() or "critique" in final_text.lower())
        changed = base_text != final_text
        if changed and (used_memory or used_web) and used_verify:
            verdict = "agentic_difference_visible"
            plain = "The final answer differs from base mode and shows retrieval plus verification behavior."
        elif changed and (used_memory or used_web):
            verdict = "retrieval_difference_visible"
            plain = "The final answer differs from base mode and uses retrieved context, but verification could be stronger."
        elif changed:
            verdict = "changed_but_tools_not_obvious"
            plain = "The final answer differs from base mode, but tool/memory consequence is not obvious enough."
        else:
            verdict = "no_visible_difference"
            plain = "The orchestrator did not visibly improve over base mode."
        summary = final.get("summary", {}) or {}
        return {
            "verdict": verdict,
            "plain": plain,
            "changed_text": changed,
            "word_similarity": round(similarity, 3),
            "memory_hits_available": len(memory_hits),
            "web_evidence_count": len(web_evidence),
            "used_memory": used_memory,
            "used_web": used_web,
            "used_verify": used_verify,
            "avg_gate": summary.get("avg_gate"),
            "avg_latent_share": summary.get("avg_latent_share"),
            "last_control": summary.get("last_control"),
            "base_tok_per_sec": round(base.get("tok_per_sec", 0), 3),
            "command_tok_per_sec": round(final.get("tok_per_sec", 0), 3),
        }


def register_agent_routes(app: Any, orchestrator: ActionOrchestrator) -> None:
    @app.post("/api/agent/run")
    def agent_run(req: AgentRunRequest):
        return orchestrator.run(req)
