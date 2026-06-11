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


GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|yo|sup|howdy|hiya|good\s+(morning|afternoon|evening|day)|"
    r"what'?s\s+up|how\s+are\s+you|how'?s\s+it\s+going|thanks?|thank\s+you|ok(ay)?|cool|nice)"
    r"\b[\s!,.?😀-🙏]*$",
    re.IGNORECASE,
)


def classify_command(command: str) -> str:
    """Cheap command profile: social | question | task.

    Social commands (greetings, thanks, one-word pleasantries) answer directly
    without the full retrieve/verify machinery — running a three-segment
    evidence loop on "Hello" is how agents end up lecturing people about
    their own architecture.
    """
    # Question marks across scripts: ASCII, fullwidth CJK, Spanish, Arabic, Greek, Armenian.
    QMARKS = "?？¿؟;՞"
    c = command.strip()
    if GREETING_RE.match(c):
        return "social"
    words = c.split()
    if len(words) <= 4 and not any(ch in c for ch in QMARKS) and len(c) < 30:
        lowered = c.lower()
        if any(w in lowered for w in ("hi", "hello", "hey", "thanks", "thank", "bye", "goodbye", "morning", "evening")):
            return "social"
    if c.endswith(tuple(QMARKS)) and len(words) <= 16:
        return "question"
    return "task"


def merge_segment(draft: str, new_text: str) -> tuple:
    """Append a segment to the draft, trimming repetition.

    Small models often re-emit the existing draft despite instructions.
    Returns (text_to_append, was_pure_repetition). Pure repetition is a
    stop signal — the model has nothing left to add.
    """
    d, n = draft.strip(), new_text.strip()
    if not d or not n:
        return n, False
    dn = re.sub(r"\s+", " ", d.lower())
    nn = re.sub(r"\s+", " ", n.lower())
    if nn in dn:
        return "", True
    n_words = nn.split()
    d_set = set(dn.split())
    if n_words and sum(1 for w in n_words if w in d_set) / len(n_words) >= 0.9:
        return "", True
    # trim word-level overlap where the segment restarts from the draft's tail
    dw, nw = d.split(), n.split()
    k = min(len(dw), len(nw), 60)
    while k >= 4:
        if [w.lower() for w in dw[-k:]] == [w.lower() for w in nw[:k]]:
            return " ".join(nw[k:]), False
        k -= 1
    return n, False


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
    SELF_REFERENT = ("lolm", "nfet", "agent", "yourself", "who are you", "what are you",
                     "this ai", "your notes", "your memory", "your goals", "workspace")

    @classmethod
    def _wants_identity(cls, command: str) -> bool:
        lowered = command.lower()
        return any(term in lowered for term in cls.SELF_REFERENT)

    def _initial_memory(self, command: str) -> List[Dict[str, Any]]:
        """Context for the drafting engine — relevance-gated.

        Identity and goals describe the workspace itself; injecting them into
        every run drags small models off-topic (a bare greeting turns into a
        lecture about the workspace). They are included only when the command
        actually references the agent/workspace. Notes are keyword-gated by
        the memory search already.
        """
        memory = self.deps.memory
        hits: List[Dict[str, Any]] = []
        if self._wants_identity(command):
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
            "You are the drafting engine of an agent. Compose the working draft of the "
            "answer to the COMMAND, one segment at a time. Stay strictly on the "
            "command's topic; treat LOCAL MEMORY and EVIDENCE as optional background, "
            "not as the subject. If the command is conversational (a greeting or small "
            "talk), just respond naturally and briefly. Never repeat the existing "
            "draft; continue it from where it stops."
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

    def _scored_notes(self, command: str, limit: int = 4,
                      min_matches: int = 2) -> List[Dict[str, Any]]:
        """Relevance-ranked scan of the WHOLE note store.

        Score = (matched substantive words) x importance weight, so a vault
        import of hundreds of notes still surfaces the right ones — recency
        is only a tiebreak, never a reason to inject something off-topic.
        Returns nothing for conversational input.
        """
        words = {w for w in re.split(r"\W+", command.lower()) if len(w) > 3}
        if not words:
            return []
        scored = []
        for idx, note in enumerate(self.deps.memory.recent_notes(limit=100_000)):
            text = (note.get("text") or "").lower()
            matches = sum(1 for w in words if w in text)
            if matches >= min(min_matches, len(words)):
                weight = 1.0 + 0.15 * (int(note.get("importance", 3)) - 3)
                scored.append((matches * weight, idx, note))
        scored.sort(key=lambda triple: (triple[0], triple[1]), reverse=True)
        return [note for _, _, note in scored[:limit]]

    @staticmethod
    def _rank_notes(notes: List[Dict[str, Any]], command: str, limit: int = 6) -> List[Dict[str, Any]]:
        """Order AND-search hits by relevance x importance instead of recency."""
        words = {w for w in re.split(r"\W+", command.lower()) if len(w) > 3}

        def score(note: Dict[str, Any]) -> float:
            text = (note.get("text") or "").lower()
            matches = sum(1 for w in words if w in text) if words else 0
            return matches * (1.0 + 0.15 * (int(note.get("importance", 3)) - 3))

        return sorted(notes, key=score, reverse=True)[:limit]

    def _do_retrieve(self, command: str, draft: str, req: NFETAgentRequest) -> List[Dict[str, Any]]:
        query = self._focus_query(command, draft)
        rows: List[Dict[str, Any]] = []
        # search_notes AND-matches every query token, so fall back from the
        # focused query to the bare command to scored token overlap. No blind
        # recency fallback: off-topic notes hijack small models, and "found
        # nothing relevant" is an honest, useful outcome.
        notes = self.deps.memory.search_notes(query, limit=12)
        if not notes:
            notes = self.deps.memory.search_notes(command, limit=12)
        if not notes:
            notes = self._scored_notes(command)
        notes = self._rank_notes(notes, command)
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
            "You are the verifier of an agent. Check the draft against the command "
            "and evidence. Start your reply with 'VERDICT: ok' or 'VERDICT: revise', "
            "then list concrete problems and fixes."
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

    @staticmethod
    def _trim_to_sentence(text: str) -> str:
        """Cut a token-capped answer back to its last complete sentence."""
        trimmed = text.rstrip()
        if not trimmed or trimmed[-1] in ".!?…\"')]":
            return trimmed
        cut = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
        if cut >= len(trimmed) * 0.5:
            return trimmed[: cut + 1]
        return trimmed

    def _do_finalize(self, command: str, draft: str, evidence: List[Dict[str, Any]],
                     req: NFETAgentRequest, profile: str = "task",
                     ) -> Generator[Dict[str, Any], None, SegmentResult]:
        ChatMessage = self.deps.ChatMessage
        if profile == "social":
            system = (
                "You are a friendly assistant. Reply to the COMMAND naturally in one "
                "or two short sentences. No sections, no meta commentary."
            )
            user = f"COMMAND:\n{command}"
        else:
            # The model writes ONLY the answer. What the agent did (notes used,
            # checks run) is reported by the harness from the action log — a
            # model-written provenance section can be confabulated; this cannot.
            system = (
                "You are the finalizer of an agent. Using the working draft and the "
                "evidence, write the final answer to the COMMAND as clear, complete "
                "prose. Write ONLY the answer itself — no section headers, no lists "
                "of what you used or verified, no commentary about your process. "
                "The system reports provenance separately."
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
        if int(result.raw.get("tokens") or 0) >= req.final_tokens:
            trimmed = self._trim_to_sentence(result.text)
            if trimmed and trimmed != result.text:
                result.text = trimmed
                result.raw["response"] = trimmed
                result.raw["truncation_trimmed"] = True
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

        profile = classify_command(command)
        # Direct questions rarely need a long draft; tasks get the full budget.
        effective_segments = (min(req.max_segments, 2) if profile == "question"
                              else req.max_segments)
        yield {"event": "run_start", "data": {
            "command": command, "reasoner": req.reasoner, "head_trained": head_trained,
            "memory_hits": len(memory_hits), "max_segments": effective_segments,
            "segment_tokens": req.segment_tokens, "profile": profile,
        }}

        if profile == "social":
            # Greetings and small talk answer directly — running the full
            # evidence loop on "Hello" is how agents end up lecturing people
            # about their own architecture.
            decision = ControlDecision(
                CONTROL_FINALIZE, "finalize", "profile",
                "conversational command — answering directly", {}, step=0,
            )
            entry = {"segment": 0, "decision": decision.to_dict(),
                     "segment_tokens": 0, "telemetry_frames": 0,
                     "action": {"kind": "finalize"}}
            timeline.append(entry)
            yield {"event": "decision", "data": entry}
            yield {"event": "action", "data": {"segment": 0, **entry["action"]}}
            ended_by = "social_direct"
            segments_iter = []
        else:
            segments_iter = range(effective_segments)

        for seg_idx in segments_iter:
            yield {"event": "segment_start", "data": {"segment": seg_idx + 1}}
            segment = yield from self._collect_stream(
                self._segment_messages(command, draft, memory_hits, evidence),
                req, tokens=req.segment_tokens, channel="draft", segment=seg_idx + 1,
            )
            counters.segments += 1
            counters.tokens += int(segment.raw.get("tokens") or 0)
            policy.observe_all(segment.frames)
            all_frames.extend(segment.frames)
            fresh, repeated = merge_segment(draft, segment.text)
            if repeated and seg_idx >= 1:
                # The model re-emitted the draft: it has nothing left to add.
                # That is a stop signal, not content.
                decision = ControlDecision(
                    CONTROL_FINALIZE, "finalize", "repetition",
                    "the draft stopped adding new content — finishing", {},
                    step=policy.frames_seen,
                )
                entry = {"segment": seg_idx + 1, "decision": decision.to_dict(),
                         "segment_tokens": segment.raw.get("tokens"),
                         "telemetry_frames": len(segment.frames),
                         "action": {"kind": "finalize"}}
                timeline.append(entry)
                yield {"event": "decision", "data": entry}
                yield {"event": "action", "data": {"segment": seg_idx + 1, **entry["action"]}}
                ended_by = "repetition_stall"
                break
            if fresh:
                draft = (draft + "\n" + fresh).strip() if draft else fresh

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
                fresh, _ = merge_segment(draft, chosen.text)
                if fresh:
                    draft = (draft + "\n" + fresh).strip() if draft else fresh
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
        # no for/else: ended_by defaults to segment_budget, break paths set
        # their own, and an empty social iterator must keep social_direct

        yield {"event": "phase", "data": {"phase": "finalize", "ended_by": ended_by}}
        final = yield from self._do_finalize(command, draft, evidence, req, profile=profile)
        counters.tokens += int(final.raw.get("tokens") or 0)

        # Provenance is assembled from the action log, never written by the
        # model — an agent that cannot misreport what it did.
        provenance: List[str] = []
        notes_used = sum(int(t["action"].get("added") or 0) for t in timeline
                         if t["action"]["kind"] == "retrieve")
        if counters.retrieves and notes_used:
            provenance.append(f"Checked local notes — used {notes_used}")
        elif counters.retrieves:
            provenance.append("Checked local notes — none were relevant, so none were used")
        verdicts = [t["action"].get("verdict") for t in timeline if t["action"]["kind"] == "verify"]
        if verdicts:
            provenance.append("Self-checked the draft — " + ", ".join(v or "?" for v in verdicts))
        if counters.branches:
            provenance.append("Explored alternative drafts, kept the steadier one")
        if ended_by == "nfet_finalize":
            provenance.append("Decided on its own when to stop")
        elif ended_by == "repetition_stall":
            provenance.append("Stopped when the draft had nothing new to add")
        elif ended_by == "social_direct":
            provenance.append("Recognized a greeting — answered directly, skipped the machinery")

        # Base-mode comparison shot runs LAST: the proof only needs it at the
        # end, and running it first would delay time-to-first-token (and
        # disconnect detection) by a full silent generation.
        yield {"event": "phase", "data": {"phase": "base_comparison"}}
        base = self._generate_base(command, req)
        proof = self._proof(base, final, memory_hits, evidence, timeline, head_trained,
                            ended_by, profile=profile)

        learning = {
            "type": "nfet_agent_run",
            "timestamp": started,
            "command": command,
            "reasoner": req.reasoner,
            "profile": profile,
            "head_trained": head_trained,
            "counters": counters.to_dict(),
            "ended_by": ended_by,
            "provenance": provenance,
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
            "profile": profile,
            "head_trained": head_trained,
            "memory_used": memory_hits,
            "evidence": evidence,
            "draft": draft,
            "result": final.raw,
            "base": base.raw,
            "timeline": timeline,
            "counters": counters.to_dict(),
            "ended_by": ended_by,
            "provenance": provenance,
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
               head_trained: bool, ended_by: str, profile: str = "task") -> Dict[str, Any]:
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
        if profile == "social":
            verdict = "social_direct_reply"
            plain = (
                "Simple conversational command — the agent recognized it and answered "
                "directly instead of running the full machinery."
            )
        elif changed and acted:
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
            "profile": profile,
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
