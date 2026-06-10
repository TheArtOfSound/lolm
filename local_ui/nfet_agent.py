"""NFET agent: the control loop where latent telemetry drives real actions.

Everything else in this repository prepares for this file. The graft computes
control logits over five actions on every token; the generation loop streams
them as telemetry; until now nothing acted on them. This agent generates in
segments and, at each segment boundary, lets the NFET control policy decide
what happens next:

    continue  -> keep drafting
    retrieve  -> search local memory (and optionally the web) mid-run and
                 inject the evidence into the working context
    verify    -> run a verification pass over the draft; critiques feed back
                 into the next segment
    branch    -> fork alternative continuations, keep the one with the
                 healthiest telemetry
    finalize  -> stop drafting and produce the polished answer

Decisions come from the calibrated heuristic policy until the control head is
trained (scripts/train_nfet_controller.py); a confident trained head takes
over decision-by-decision. Every run logs (telemetry -> decision -> outcome)
tuples to the improvement log — the training data that improves the head.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional

from pydantic import BaseModel

from lolm.nfet_policy import (
    CONTROL_BRANCH,
    CONTROL_CONTINUE,
    CONTROL_FINALIZE,
    CONTROL_LABELS,
    CONTROL_RETRIEVE,
    CONTROL_VERIFY,
    ControlDecision,
    NFETControlPolicy,
    PolicyConfig,
    TelemetryFrame,
)


class NFETAgentRequest(BaseModel):
    command: str
    reasoner: str = "local"          # "local" | "claude" (frontier voice, local monitor)
    max_segments: int = 6
    segment_tokens: int = 48
    max_retrieves: int = 2
    max_verifies: int = 2
    max_branches: int = 1
    branch_width: int = 2
    final_tokens: int = 200
    temperature: float = 0.35
    branch_temperature: float = 0.8
    top_p: float = 0.9
    use_graft: bool = True
    ablation_mode: str = "full"
    allow_web: bool = False
    web_limit: int = 3


@dataclass
class SegmentResult:
    text: str
    frames: List[TelemetryFrame]
    last_control_logits: Optional[List[float]]
    hit_eos: bool
    raw: Dict[str, Any]
    mean_entropy: float = 0.0


@dataclass
class RunCounters:
    retrieves: int = 0
    verifies: int = 0
    branches: int = 0
    segments: int = 0
    tokens: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "segments": self.segments,
            "tokens": self.tokens,
            "retrieves": self.retrieves,
            "verifies": self.verifies,
            "branches": self.branches,
        }


@dataclass
class AgentDeps:
    """Injected dependencies so the loop is testable without a model."""

    memory: Any
    ChatMessage: Any
    ChatRequest: Any
    generation_loop: Callable[[Any], Iterator[Dict[str, Any]]]
    append_event: Callable[[Dict[str, Any]], None]
    head_trained_fn: Callable[[], bool] = lambda: False
    web_search: Optional[Callable[..., Dict[str, Any]]] = None
    fetch_url: Optional[Callable[..., Dict[str, Any]]] = None
    frontier_loop: Optional[Callable[[Any], Iterator[Dict[str, Any]]]] = None


class NFETAgent:
    """Latent-telemetry-driven agent loop."""

    def __init__(self, deps: AgentDeps, policy_config: Optional[PolicyConfig] = None):
        self.deps = deps
        self.policy_config = policy_config
        self.last_run: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Generation plumbing
    # ------------------------------------------------------------------
    def _loop_for(self, req: NFETAgentRequest) -> Callable[[Any], Iterator[Dict[str, Any]]]:
        if req.reasoner == "claude":
            if self.deps.frontier_loop is None:
                raise RuntimeError(
                    "reasoner='claude' requested but no frontier loop is configured "
                    "(install the anthropic SDK and set ANTHROPIC_API_KEY)"
                )
            return self.deps.frontier_loop
        return self.deps.generation_loop

    def _collect_stream(self, messages: List[Any], req: NFETAgentRequest, *, tokens: int,
                        temperature: Optional[float] = None, use_graft: Optional[bool] = None,
                        channel: Optional[str] = None, segment: Optional[int] = None,
                        ) -> Generator[Dict[str, Any], None, SegmentResult]:
        """Drive one generation call; yield compact token events, return the result.

        When ``channel`` is None the call is silent (no token events) — used for
        the base-mode comparison shot.
        """
        chat_req = self.deps.ChatRequest(
            messages=messages,
            max_new_tokens=tokens,
            temperature=req.temperature if temperature is None else temperature,
            top_p=req.top_p,
            use_graft=req.use_graft if use_graft is None else use_graft,
            ablation_mode=req.ablation_mode,
        )
        text = ""
        frames: List[TelemetryFrame] = []
        last_logits: Optional[List[float]] = None
        token_count = 0
        final: Optional[Dict[str, Any]] = None
        started = time.perf_counter()
        for event in self._loop_for(req)(chat_req):
            kind = event.get("event")
            data = event.get("data", {})
            if kind == "error":
                raise RuntimeError(data.get("error", "generation failed"))
            if kind == "token":
                text += data.get("token", "")
                token_count += 1
                trace = data.get("trace") or {}
                if trace.get("used_graft"):
                    frames.append(TelemetryFrame.from_trace(trace, step=token_count))
                    logits = trace.get("control_logits")
                    if isinstance(logits, list) and logits:
                        last_logits = [float(x) for x in logits]
                if channel is not None:
                    compact: Dict[str, Any] = {"token": data.get("token", ""), "channel": channel}
                    if segment is not None:
                        compact["segment"] = segment
                    if trace.get("used_graft"):
                        compact["nfet"] = {
                            "entropy": trace.get("graft_entropy"),
                            "drift": trace.get("hidden_drift"),
                            "gate": trace.get("gate_mean"),
                            "regime": trace.get("regime_entropy"),
                            "control": trace.get("control"),
                        }
                    yield {"event": "token", "data": compact}
            if kind == "done":
                final = data
        elapsed = max(time.perf_counter() - started, 1e-9)
        if final is None:
            final = {"response": text, "tokens": token_count}
        final["seconds"] = elapsed
        final["tok_per_sec"] = token_count / elapsed
        hit_eos = token_count < tokens
        mean_entropy = (
            sum(f.logit_entropy for f in frames) / len(frames) if frames else 0.0
        )
        clean = (final.get("response") or text or "").strip()
        return SegmentResult(
            text=clean, frames=frames, last_control_logits=last_logits,
            hit_eos=hit_eos, raw=final, mean_entropy=mean_entropy,
        )

    def _collect(self, messages: List[Any], req: NFETAgentRequest, *, tokens: int,
                 temperature: Optional[float] = None, use_graft: Optional[bool] = None) -> SegmentResult:
        gen = self._collect_stream(messages, req, tokens=tokens, temperature=temperature,
                                   use_graft=use_graft, channel=None)
        while True:
            try:
                next(gen)
            except StopIteration as stop:
                return stop.value

    # ------------------------------------------------------------------
    # Context construction
    # ------------------------------------------------------------------
    def _initial_memory(self, command: str) -> List[Dict[str, Any]]:
        memory = self.deps.memory
        hits: List[Dict[str, Any]] = []
        identity = memory.read_identity().strip()
        if identity:
            hits.append({"kind": "identity", "text": identity[-1200:], "meta": {}})
        goals = [g for g in memory.get_goals() if g.get("status", "active") == "active"]
        for goal in sorted(goals, key=lambda g: int(g.get("priority", 3)), reverse=True)[:6]:
            hits.append({"kind": "goal", "text": goal.get("title", ""), "meta": {"why": goal.get("why", "")}})
        for note in memory.search_notes(command, limit=8):
            hits.append({"kind": "memory", "text": note.get("text", ""), "meta": {"tag": note.get("tag")}})
        return [h for h in hits if h.get("text")][:12]

    @staticmethod
    def _evidence_block(label: str, rows: List[Dict[str, Any]], limit: int = 6000) -> str:
        if not rows:
            return f"{label}: none"
        out = [f"{label}:"]
        for row in rows:
            url = f" url={row.get('url')}" if row.get("url") else ""
            out.append(f"[{row.get('kind', 'item')}{url}] {row.get('text', '')}")
        return "\n".join(out)[:limit]

    def _segment_messages(self, command: str, draft: str, memory_hits: List[Dict[str, Any]],
                          evidence: List[Dict[str, Any]]) -> List[Any]:
        ChatMessage = self.deps.ChatMessage
        system = (
            "You are the drafting engine of the LOLM-NFET agent. Compose the working "
            "draft of the answer, one segment at a time. Use evidence when given. "
            "Never repeat the existing draft; continue it from where it stops."
        )
        user = f"""COMMAND:
{command}

{self._evidence_block('LOCAL MEMORY', memory_hits)}

{self._evidence_block('EVIDENCE GATHERED THIS RUN', evidence)}

DRAFT SO FAR:
{draft if draft.strip() else '(empty — start the draft)'}

Continue the draft. Write the next segment only."""
        return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------
    @staticmethod
    def _focus_query(command: str, draft: str) -> str:
        tail = re.sub(r"\s+", " ", draft).strip()[-240:]
        return f"{command} {tail}".strip()[:400]

    def _do_retrieve(self, command: str, draft: str, req: NFETAgentRequest) -> List[Dict[str, Any]]:
        query = self._focus_query(command, draft)
        rows: List[Dict[str, Any]] = []
        # search_notes AND-matches every query token, so fall back from the
        # focused query to the bare command to recent important notes.
        notes = self.deps.memory.search_notes(query, limit=6)
        if not notes:
            notes = self.deps.memory.search_notes(command, limit=6)
        if not notes:
            notes = self.deps.memory.recent_notes(limit=4, min_importance=4)
        for note in notes:
            rows.append({"kind": "memory", "text": note.get("text", ""), "meta": {"tag": note.get("tag")}})
        if req.allow_web and self.deps.web_search is not None:
            try:
                results = self.deps.web_search(query, limit=req.web_limit)
                for item in results.get("results", [])[: req.web_limit]:
                    rows.append({
                        "kind": "web", "title": item.get("title", ""),
                        "url": item.get("url", ""), "text": item.get("snippet", ""),
                    })
            except Exception as exc:
                rows.append({"kind": "web_error", "text": str(exc)[:200]})
        return [r for r in rows if r.get("text")]

    def _do_verify(self, command: str, draft: str, evidence: List[Dict[str, Any]],
                   req: NFETAgentRequest) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        ChatMessage = self.deps.ChatMessage
        system = (
            "You are the verifier of the LOLM-NFET agent. Check the draft against the "
            "command and evidence. Start your reply with 'VERDICT: ok' or "
            "'VERDICT: revise', then list concrete problems and fixes."
        )
        user = f"""COMMAND:
{command}

{self._evidence_block('EVIDENCE', evidence)}

DRAFT:
{draft}"""
        seg = yield from self._collect_stream(
            [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
            req, tokens=min(req.segment_tokens * 2, 128), channel="verify",
        )
        lower = seg.text.lower()
        verdict = "revise" if "revise" in lower.split("verdict:")[-1][:40] else "ok"
        return {"verdict": verdict, "notes": seg.text, "raw_id": seg.raw.get("id")}

    def _do_branch(self, command: str, draft: str, memory_hits: List[Dict[str, Any]],
                   evidence: List[Dict[str, Any]], req: NFETAgentRequest,
                   ) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        candidates: List[SegmentResult] = []
        for k in range(max(req.branch_width, 2)):
            candidate = yield from self._collect_stream(
                self._segment_messages(command, draft, memory_hits, evidence),
                req, tokens=req.segment_tokens, temperature=req.branch_temperature,
                channel=f"branch:{k}",
            )
            candidates.append(candidate)
        # Healthiest continuation = lowest mean logit entropy (most confident);
        # candidates without telemetry rank last.
        def score(seg: SegmentResult) -> float:
            return seg.mean_entropy if seg.frames else float("inf")
        best_idx = min(range(len(candidates)), key=lambda i: score(candidates[i]))
        return {
            "chosen": best_idx,
            "candidates": [
                {"text": c.text, "mean_entropy": round(c.mean_entropy, 4), "tokens": c.raw.get("tokens")}
                for c in candidates
            ],
            "segment": candidates[best_idx],
        }

    def _do_finalize(self, command: str, draft: str, evidence: List[Dict[str, Any]],
                     req: NFETAgentRequest) -> Generator[Dict[str, Any], None, SegmentResult]:
        ChatMessage = self.deps.ChatMessage
        system = (
            "You are the finalizer of the LOLM-NFET agent. Turn the working draft into "
            "the final answer. Sections: Result, What I used, What I verified, Limits, "
            "Next action. Be concrete; do not claim actions that are not in evidence."
        )
        user = f"""COMMAND:
{command}

{self._evidence_block('EVIDENCE', evidence)}

WORKING DRAFT:
{draft}"""
        result = yield from self._collect_stream(
            [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
            req, tokens=req.final_tokens, channel="final",
        )
        return result

    def _generate_base(self, command: str, req: NFETAgentRequest) -> SegmentResult:
        ChatMessage = self.deps.ChatMessage
        return self._collect(
            [
                ChatMessage(role="system", content="You are a normal local chatbot. Answer the user directly."),
                ChatMessage(role="user", content=command),
            ],
            req, tokens=min(req.final_tokens, 96), use_graft=False,
        )

    # ------------------------------------------------------------------
    # Budget arbitration
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_budget(decision: ControlDecision, counters: RunCounters,
                      req: NFETAgentRequest) -> ControlDecision:
        limits = {
            CONTROL_RETRIEVE: counters.retrieves < req.max_retrieves,
            CONTROL_VERIFY: counters.verifies < req.max_verifies,
            CONTROL_BRANCH: counters.branches < req.max_branches,
        }
        if decision.control in limits and not limits[decision.control]:
            return ControlDecision(
                CONTROL_CONTINUE, "continue", "budget",
                f"{decision.label} budget exhausted; continuing (was: {decision.reason})",
                decision.zscores, head_probs=decision.head_probs, step=decision.step,
            )
        return decision

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run_events(self, req: NFETAgentRequest) -> Iterator[Dict[str, Any]]:
        """The agent loop as a live event stream.

        Event protocol (each item ``{"event": ..., "data": ...}``):
            run_start      command, reasoner, head_trained, memory hits
            phase          base_comparison | finalize
            segment_start  segment index
            token          streamed text with channel (draft/verify/branch:k/final)
            decision       NFET control decision with z-scores and source
            action         what the decision did (evidence added, verdict, ...)
            proof          the proof receipt
            run_done       the full result payload (same shape run() returns)
        """
        command = req.command.strip()
        if not command:
            yield {"event": "error", "data": {"error": "empty command"}}
            return

        started = time.time()
        head_trained = bool(self.deps.head_trained_fn())
        policy = NFETControlPolicy(self.policy_config)
        memory_hits = self._initial_memory(command)
        evidence: List[Dict[str, Any]] = []
        counters = RunCounters()
        timeline: List[Dict[str, Any]] = []
        all_frames: List[TelemetryFrame] = []
        draft = ""
        ended_by = "segment_budget"

        yield {"event": "run_start", "data": {
            "command": command, "reasoner": req.reasoner, "head_trained": head_trained,
            "memory_hits": len(memory_hits), "max_segments": req.max_segments,
            "segment_tokens": req.segment_tokens,
        }}
        yield {"event": "phase", "data": {"phase": "base_comparison"}}
        base = self._generate_base(command, req)

        for seg_idx in range(req.max_segments):
            yield {"event": "segment_start", "data": {"segment": seg_idx + 1}}
            segment = yield from self._collect_stream(
                self._segment_messages(command, draft, memory_hits, evidence),
                req, tokens=req.segment_tokens, channel="draft", segment=seg_idx + 1,
            )
            counters.segments += 1
            counters.tokens += int(segment.raw.get("tokens") or 0)
            policy.observe_all(segment.frames)
            all_frames.extend(segment.frames)
            draft = (draft + "\n" + segment.text).strip() if draft else segment.text

            decision = policy.decide(
                control_logits=segment.last_control_logits, head_trained=head_trained,
            )
            decision = self._apply_budget(decision, counters, req)
            entry: Dict[str, Any] = {
                "segment": seg_idx + 1,
                "decision": decision.to_dict(),
                "segment_tokens": segment.raw.get("tokens"),
                "segment_mean_entropy": round(segment.mean_entropy, 4),
                "telemetry_frames": len(segment.frames),
            }
            yield {"event": "decision", "data": entry}

            if decision.control == CONTROL_RETRIEVE:
                counters.retrieves += 1
                new_evidence = self._do_retrieve(command, draft, req)
                evidence.extend(new_evidence)
                entry["action"] = {"kind": "retrieve", "added": len(new_evidence),
                                   "evidence": new_evidence[:6]}
            elif decision.control == CONTROL_VERIFY:
                counters.verifies += 1
                verdict = yield from self._do_verify(command, draft, evidence, req)
                entry["action"] = {"kind": "verify", "verdict": verdict["verdict"]}
                if verdict["verdict"] == "revise":
                    evidence.append({
                        "kind": "verifier_note",
                        "text": f"A verification pass flagged the draft: {verdict['notes'][:600]}",
                    })
            elif decision.control == CONTROL_BRANCH:
                counters.branches += 1
                branch = yield from self._do_branch(command, draft, memory_hits, evidence, req)
                chosen: SegmentResult = branch["segment"]
                policy.observe_all(chosen.frames)
                all_frames.extend(chosen.frames)
                counters.tokens += int(chosen.raw.get("tokens") or 0)
                draft = (draft + "\n" + chosen.text).strip()
                entry["action"] = {
                    "kind": "branch", "chosen": branch["chosen"],
                    "candidates": branch["candidates"],
                }
            elif decision.control == CONTROL_FINALIZE:
                entry["action"] = {"kind": "finalize"}
                timeline.append(entry)
                yield {"event": "action", "data": {"segment": seg_idx + 1, **entry["action"]}}
                ended_by = "nfet_finalize"
                break
            else:
                entry["action"] = {"kind": "continue"}

            timeline.append(entry)
            yield {"event": "action", "data": {"segment": seg_idx + 1, **entry["action"]}}
            if segment.hit_eos and decision.control == CONTROL_CONTINUE and seg_idx >= 1:
                ended_by = "natural_eos"
                break
        else:
            ended_by = "segment_budget"

        yield {"event": "phase", "data": {"phase": "finalize", "ended_by": ended_by}}
        final = yield from self._do_finalize(command, draft, evidence, req)
        counters.tokens += int(final.raw.get("tokens") or 0)
        proof = self._proof(base, final, memory_hits, evidence, timeline, head_trained, ended_by)

        learning = {
            "type": "nfet_agent_run",
            "timestamp": started,
            "command": command,
            "reasoner": req.reasoner,
            "head_trained": head_trained,
            "counters": counters.to_dict(),
            "ended_by": ended_by,
            "timeline": timeline,
            "frames": [
                {
                    "logit_entropy": round(f.logit_entropy, 4),
                    "hidden_drift": round(f.hidden_drift, 5),
                    "gate_mean": round(f.gate_mean, 4),
                    "regime_entropy": round(f.regime_entropy, 4),
                    "step": f.step,
                }
                for f in all_frames
            ],
            "final_id": final.raw.get("id"),
            "base_id": base.raw.get("id"),
            "proof": proof,
        }
        self.deps.append_event(learning)
        self.deps.memory.append_journal(
            f"## NFET Agent Run\n\nCommand: {command}\n\nVerdict: {proof['verdict']}\n\n"
            f"Controls: {proof['control_counts']} (source: {proof['decision_sources']})\n\n"
            f"Ended by: {ended_by}"
        )

        result = {
            "command": command,
            "reasoner": req.reasoner,
            "head_trained": head_trained,
            "memory_used": memory_hits,
            "evidence": evidence,
            "draft": draft,
            "result": final.raw,
            "base": base.raw,
            "timeline": timeline,
            "counters": counters.to_dict(),
            "ended_by": ended_by,
            "proof": proof,
            "saved_learning_type": "nfet_agent_run",
        }
        self.last_run = result
        yield {"event": "proof", "data": proof}
        yield {"event": "run_done", "data": result}

    def run(self, req: NFETAgentRequest) -> Dict[str, Any]:
        """Run the loop to completion and return the final payload."""
        result: Optional[Dict[str, Any]] = None
        error: Optional[Dict[str, Any]] = None
        for event in self.run_events(req):
            if event["event"] == "run_done":
                result = event["data"]
            elif event["event"] == "error":
                error = event["data"]
        if result is not None:
            return result
        return error or {"error": "run produced no result"}

    # ------------------------------------------------------------------
    # Proof receipt
    # ------------------------------------------------------------------
    @staticmethod
    def _proof(base: SegmentResult, final: SegmentResult, memory_hits: List[Dict[str, Any]],
               evidence: List[Dict[str, Any]], timeline: List[Dict[str, Any]],
               head_trained: bool, ended_by: str) -> Dict[str, Any]:
        base_text = base.text.strip()
        final_text = final.text.strip()
        base_words = set(base_text.lower().split())
        final_words = set(final_text.lower().split())
        similarity = len(base_words & final_words) / max(len(base_words | final_words), 1)

        control_counts: Dict[str, int] = {}
        decision_sources: Dict[str, int] = {}
        for entry in timeline:
            decision = entry.get("decision", {})
            label = decision.get("label", "?")
            source = decision.get("source", "?")
            control_counts[label] = control_counts.get(label, 0) + 1
            decision_sources[source] = decision_sources.get(source, 0) + 1

        acted = any(
            entry.get("action", {}).get("kind") in {"retrieve", "verify", "branch"}
            for entry in timeline
        )
        nfet_ended = ended_by == "nfet_finalize"
        changed = base_text != final_text
        if changed and acted:
            verdict = "nfet_control_visible"
            plain = (
                "NFET control decisions changed the run: the agent retrieved, verified, "
                "or branched mid-generation, and the final answer differs from base mode."
            )
        elif changed and nfet_ended:
            verdict = "nfet_finalize_visible"
            plain = "NFET decided when to stop, and the final answer differs from base mode."
        elif changed:
            verdict = "changed_but_controls_quiet"
            plain = "The answer differs from base mode, but NFET control stayed on continue."
        else:
            verdict = "no_visible_difference"
            plain = "The agent did not visibly improve over base mode."
        return {
            "verdict": verdict,
            "plain": plain,
            "changed_text": changed,
            "word_similarity": round(similarity, 3),
            "control_counts": control_counts,
            "decision_sources": decision_sources,
            "actions_taken": acted,
            "ended_by": ended_by,
            "head_trained": head_trained,
            "memory_hits_available": len(memory_hits),
            "evidence_count": len(evidence),
            "base_tok_per_sec": round(base.raw.get("tok_per_sec", 0), 3),
            "final_tok_per_sec": round(final.raw.get("tok_per_sec", 0), 3),
        }


def sse_event(event: str, data: Dict[str, Any]) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def register_nfet_agent_routes(app: Any, agent: NFETAgent) -> None:
    from fastapi.responses import StreamingResponse

    @app.post("/api/agent/nfet/run")
    def nfet_agent_run(req: NFETAgentRequest):
        return agent.run(req)

    @app.post("/api/agent/nfet/run/stream")
    def nfet_agent_run_stream(req: NFETAgentRequest):
        def events() -> Iterator[str]:
            for item in agent.run_events(req):
                yield sse_event(item["event"], item["data"])
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/agent/nfet/last")
    def nfet_agent_last():
        return {"last_run": agent.last_run}
