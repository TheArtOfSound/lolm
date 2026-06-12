from __future__ import annotations

import json
import random
from typing import Any, Dict, Iterator, List

from local_ui.memory_store import MemoryStore
from local_ui.nfet_agent import AgentDeps, NFETAgent, NFETAgentRequest
from lolm.nfet_policy import PolicyConfig


class Msg:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


class Req:
    def __init__(self, messages, max_new_tokens=96, temperature=0.35, top_p=0.9,
                 use_graft=True, ablation_mode="full"):
        self.messages = messages
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.use_graft = use_graft
        self.ablation_mode = ablation_mode


def frame_trace(step: int, entropy: float, drift: float = 0.05, gate: float = 0.7,
                regime: float = 2.0, control_logits=None) -> Dict[str, Any]:
    return {
        "step": step,
        "used_graft": True,
        "graft_entropy": entropy,
        "hidden_drift": drift,
        "gate_mean": gate,
        "regime_entropy": regime,
        "control_logits": control_logits or [0.1, 0.1, 0.1, 0.1, 0.1],
    }


def segment_spec(entropies: List[float], text: str, *, drift: float = 0.05,
                 regime: float = 2.0, drifts: List[float] | None = None,
                 eos: bool = False) -> Dict[str, Any]:
    return {"entropies": entropies, "drifts": drifts, "drift": drift,
            "regime": regime, "text": text, "eos": eos}


class FakeLoop:
    """Scripted generation loop. Routes calls by system-prompt role marker."""

    def __init__(self, segments: List[Dict[str, Any]],
                 base_text: str = "base answer about latent order",
                 verify_text: str = "VERDICT: ok\nLooks fine.",
                 final_text: str = "Result: the finished answer.\nWhat I used: evidence.",
                 branch_specs: List[Dict[str, Any]] | None = None):
        self.segments = list(segments)
        self.base_text = base_text
        self.verify_text = verify_text
        self.final_text = final_text
        self.branch_specs = list(branch_specs or [])
        self.calls: List[Dict[str, Any]] = []
        self.rng = random.Random(11)
        self.counter = 0

    def _emit(self, spec: Dict[str, Any], req: Any) -> Iterator[Dict[str, Any]]:
        entropies = spec["entropies"]
        drifts = spec.get("drifts") or [spec.get("drift", 0.05)] * len(entropies)
        n = len(entropies) if spec.get("eos") else max(len(entropies), req.max_new_tokens)
        words = (spec["text"].split() or ["..."])
        for i in range(n):
            entropy = entropies[i] if i < len(entropies) else entropies[-1]
            drift = drifts[i] if i < len(drifts) else drifts[-1]
            token = (" " if i else "") + words[i % len(words)]
            yield {"event": "token", "data": {
                "token": token,
                "trace": frame_trace(i + 1, entropy + self.rng.uniform(-0.05, 0.05),
                                     drift=drift, regime=spec.get("regime", 2.0)),
            }}
        self.counter += 1
        yield {"event": "done", "data": {
            "id": f"fake-{self.counter}", "response": spec["text"],
            "tokens": n, "summary": {},
        }}

    def _plain(self, text: str, tokens: int = 8) -> Iterator[Dict[str, Any]]:
        for i in range(tokens):
            yield {"event": "token", "data": {"token": " x", "trace": {"used_graft": False}}}
        self.counter += 1
        yield {"event": "done", "data": {"id": f"fake-{self.counter}", "response": text,
                                          "tokens": tokens, "summary": {}}}

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        system = req.messages[0].content if req.messages else ""
        self.calls.append({"system": system[:200], "user": req.messages[-1].content,
                           "temperature": req.temperature, "use_graft": req.use_graft})
        if "normal local chatbot" in system:
            yield from self._plain(self.base_text)
        elif "friendly assistant" in system:
            yield from self._plain("Hi there! How can I help today?")
        elif "verifier" in system:
            yield from self._plain(self.verify_text)
        elif "finalizer" in system:
            yield from self._plain(self.final_text, tokens=24)
        elif "drafting engine" in system:
            if req.temperature > 0.5 and self.branch_specs:
                spec = self.branch_specs.pop(0)
            else:
                spec = self.segments.pop(0) if self.segments else segment_spec(
                    [1.0] * 16, "trailing calm segment", drift=0.01)
            yield from self._emit(spec, req)
        else:
            yield from self._plain("unknown role")


def make_agent(tmp_path, loop: FakeLoop, head_trained: bool = False,
               policy: PolicyConfig | None = None) -> tuple[NFETAgent, list]:
    events: List[Dict[str, Any]] = []
    memory = MemoryStore(tmp_path / "data")
    memory.append_note("LOLM separates surface tokens from latent state tracking", tag="research", importance=5)
    memory.add_goal("Ship the NFET agent", why="close the control loop", priority=5)
    deps = AgentDeps(
        memory=memory, ChatMessage=Msg, ChatRequest=Req,
        generation_loop=loop, append_event=events.append,
        head_trained_fn=lambda: head_trained,
    )
    cfg = policy or PolicyConfig(min_calibration=12, sustain=4, cooldown=16,
                                 min_steps_before_finalize=32, window=160)
    return NFETAgent(deps, policy_config=cfg), events


def test_entropy_spike_drives_retrieve_then_finalize(tmp_path):
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, "steady opening segment"),
        segment_spec([3.0] * 36 + [6.5] * 12, "uncertain segment needs evidence"),
        segment_spec([0.8] * 48, "calm confident closing segment", drift=0.01),
    ])
    agent, events = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="explain the lolm latent order model", max_segments=6))

    kinds = [t["action"]["kind"] for t in out["timeline"]]
    assert kinds[0] == "continue"
    assert kinds[1] == "retrieve"
    assert kinds[2] == "finalize"
    assert out["ended_by"] == "nfet_finalize"
    assert out["counters"]["retrieves"] == 1
    # retrieve found the memory note and injected it
    assert any(e["kind"] == "memory" for e in out["evidence"])
    # the segment after retrieve saw the evidence
    drafting_calls = [c for c in loop.calls if "drafting engine" in c["system"]]
    assert "EVIDENCE GATHERED THIS RUN" in drafting_calls[2]["user"]
    assert "latent state tracking" in drafting_calls[2]["user"]
    # proof receipt records control activity
    assert out["proof"]["verdict"] == "nfet_control_visible"
    assert out["proof"]["control_counts"].get("retrieve") == 1
    # learning event captured frames for the flywheel
    assert events and events[0]["type"] == "nfet_agent_run"
    assert len(events[0]["frames"]) >= 96
    assert json.dumps(events[0])  # serializable


def test_drift_spike_drives_verify_and_critique_feeds_back(tmp_path):
    loop = FakeLoop(
        segments=[
            segment_spec([3.0] * 48, "steady opening segment"),
            segment_spec([3.4] * 48, "drifting segment",
                         drifts=[0.05] * 36 + [0.9] * 12),
            segment_spec([3.0] * 48, "post verify segment", eos=True),
        ],
        verify_text="VERDICT: revise\nThe draft misstates the gate equation.",
    )
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="describe the gate", max_segments=5))

    kinds = [t["action"]["kind"] for t in out["timeline"]]
    assert "verify" in kinds
    verify_entry = out["timeline"][kinds.index("verify")]
    assert verify_entry["action"]["verdict"] == "revise"
    assert any(e["kind"] == "verifier_note" for e in out["evidence"])
    drafting_calls = [c for c in loop.calls if "drafting engine" in c["system"]]
    assert any("verification pass flagged" in c["user"] for c in drafting_calls)


def test_regime_collapse_drives_branch_and_picks_calmest(tmp_path):
    loop = FakeLoop(
        segments=[
            segment_spec([3.0] * 48, "steady opening segment"),
            segment_spec([3.1] * 48, "stuck segment", regime=0.1),
        ],
        branch_specs=[
            segment_spec([4.5] * 24, "wild alternative", eos=True),
            segment_spec([1.5] * 24, "calm alternative wins", eos=True),
        ],
    )
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="pick a direction", max_segments=3,
                                     max_branches=1, branch_width=2))
    kinds = [t["action"]["kind"] for t in out["timeline"]]
    assert "branch" in kinds
    branch_entry = out["timeline"][kinds.index("branch")]
    assert branch_entry["action"]["chosen"] == 1
    assert "calm alternative wins" in out["draft"]


def test_budget_exhaustion_degrades_to_continue(tmp_path):
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, "steady opening segment"),
        segment_spec([3.0] * 36 + [6.5] * 12, "spike one"),
        segment_spec([3.0] * 36 + [7.0] * 12, "spike two"),
        segment_spec([3.0] * 48, "tail", eos=True),
    ])
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="explain lolm", max_segments=5, max_retrieves=1))
    sources = [t["decision"]["source"] for t in out["timeline"]]
    kinds = [t["action"]["kind"] for t in out["timeline"]]
    assert kinds.count("retrieve") == 1
    assert "budget" in sources  # second spike got degraded
    assert out["counters"]["retrieves"] == 1


def test_forced_finalize_on_segment_budget(tmp_path):
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, f"segment number {i}") for i in range(3)
    ])
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="explain lolm", max_segments=2))
    assert out["ended_by"] == "segment_budget"
    assert out["counters"]["segments"] == 2
    assert out["result"]["response"].startswith("Result:")


def test_trained_head_decision_recorded(tmp_path):
    # Head says retrieve with high confidence on every token.
    confident_retrieve = [0.0, 8.0, 0.0, 0.0, 0.0]

    class HeadLoop(FakeLoop):
        def _emit(self, spec, req):
            for event in super()._emit(spec, req):
                trace = event.get("data", {}).get("trace")
                if trace and trace.get("used_graft"):
                    trace["control_logits"] = confident_retrieve
                yield event

    loop = HeadLoop(segments=[
        segment_spec([3.0] * 48, "steady opening segment"),
        segment_spec([3.0] * 48, "head takes over here"),
        segment_spec([3.0] * 48, "tail segment", eos=True),
    ])
    agent, _ = make_agent(tmp_path, loop, head_trained=True)
    out = agent.run(NFETAgentRequest(command="explain lolm", max_segments=4))
    sources = [t["decision"]["source"] for t in out["timeline"]]
    assert "head" in sources
    head_entry = out["timeline"][sources.index("head")]
    assert head_entry["decision"]["label"] == "retrieve"
    assert out["proof"]["decision_sources"].get("head", 0) >= 1


def test_run_events_protocol_order_and_content(tmp_path):
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, "steady opening segment"),
        segment_spec([3.0] * 36 + [6.5] * 12, "uncertain segment needs evidence"),
        segment_spec([0.8] * 48, "calm confident closing segment", drift=0.01),
    ])
    agent, _ = make_agent(tmp_path, loop)
    events = list(agent.run_events(NFETAgentRequest(command="explain the lolm latent order model")))
    names = [e["event"] for e in events]

    assert names[0] == "run_start"
    assert "segment_start" in names and "decision" in names and "action" in names
    assert names[-3:] == ["proof", "receipt", "run_done"]
    # token streaming present, channel-tagged
    token_events = [e for e in events if e["event"] == "token"]
    assert token_events, "expected streamed tokens"
    channels = {t["data"]["channel"] for t in token_events}
    assert "draft" in channels and "final" in channels
    # draft tokens carry compact nfet telemetry
    draft_tokens = [t for t in token_events if t["data"]["channel"] == "draft"]
    assert any(t["data"].get("nfet", {}).get("entropy") is not None for t in draft_tokens)
    # decisions appear before their actions per segment
    idx_decision = names.index("decision")
    idx_action = names.index("action")
    assert idx_decision < idx_action
    # run_done payload matches run() shape
    done = events[-1]["data"]
    assert done["proof"]["verdict"] == "nfet_control_visible"
    assert done["ended_by"] == "nfet_finalize"


def test_run_events_verify_streams_verify_channel(tmp_path):
    loop = FakeLoop(
        segments=[
            segment_spec([3.0] * 48, "steady opening segment"),
            segment_spec([3.4] * 48, "drifting segment", drifts=[0.05] * 36 + [0.9] * 12),
            segment_spec([3.0] * 48, "post verify segment", eos=True),
        ],
        verify_text="VERDICT: revise\nThe draft misstates the gate equation.",
    )
    agent, _ = make_agent(tmp_path, loop)
    events = list(agent.run_events(NFETAgentRequest(command="describe the gate")))
    channels = {e["data"]["channel"] for e in events if e["event"] == "token"}
    assert "verify" in channels


def test_run_collector_matches_stream(tmp_path):
    spec = [
        segment_spec([3.0] * 48, "steady opening segment"),
        segment_spec([3.0] * 48, "second segment", eos=True),
    ]
    agent1, _ = make_agent(tmp_path, FakeLoop(segments=list(spec)))
    out1 = agent1.run(NFETAgentRequest(command="explain lolm"))
    agent2, _ = make_agent(tmp_path, FakeLoop(segments=list(spec)))
    done = [e for e in agent2.run_events(NFETAgentRequest(command="explain lolm"))
            if e["event"] == "run_done"][0]["data"]
    assert out1["ended_by"] == done["ended_by"]
    assert out1["counters"] == done["counters"]
    assert out1["proof"]["verdict"] == done["proof"]["verdict"]


def test_strip_overlap_trims_repeated_segments(tmp_path):
    sentence = "The gate decides whether the latent state surfaces."
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, sentence),
        # small models often re-write the draft instead of continuing it
        segment_spec([3.0] * 48, sentence + " It matters at scale.", eos=True),
    ])
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="explain the gate", max_segments=3))
    assert out["draft"].count("The gate decides whether") == 1
    assert "It matters at scale." in out["draft"]


def test_merge_segment_overlap_and_repetition():
    from local_ui.nfet_agent import merge_segment
    # distinct continuation passes through untouched
    fresh, rep = merge_segment("First part of the draft.", "Second part entirely new.")
    assert fresh == "Second part entirely new." and rep is False
    # head-overlap with the draft tail gets trimmed
    fresh, rep = merge_segment("the gate decides what the surface stream may say",
                               "the surface stream may say and the latent stream tracks order")
    assert rep is False and fresh.startswith("and the latent stream")
    # re-emitting the draft is flagged as pure repetition
    fresh, rep = merge_segment("the gate decides per dimension what surfaces",
                               "The gate decides per dimension what surfaces")
    assert rep is True and fresh == ""


def test_identity_gated_by_command(tmp_path):
    loop = FakeLoop(segments=[segment_spec([3.0] * 48, "greeting segment", eos=True),
                              segment_spec([3.0] * 48, "second", eos=True)])
    agent, _ = make_agent(tmp_path, loop)
    agent.deps.memory.append_identity_line("This workspace is the LOLM demo box")
    out = agent.run(NFETAgentRequest(command="hello there friend", max_segments=2))
    drafting = [c for c in loop.calls if "drafting engine" in c["system"]]
    assert all("LOLM demo box" not in c["user"] for c in drafting)
    assert not any(h["kind"] == "identity" for h in out["memory_used"])

    loop2 = FakeLoop(segments=[segment_spec([3.0] * 48, "about segment", eos=True),
                               segment_spec([3.0] * 48, "second", eos=True)])
    agent2, _ = make_agent(tmp_path, loop2)
    agent2.deps.memory.append_identity_line("This workspace is the LOLM demo box")
    out2 = agent2.run(NFETAgentRequest(command="what are you, agent?", max_segments=2))
    assert any(h["kind"] == "identity" for h in out2["memory_used"])


def test_truncated_final_trimmed_to_sentence(tmp_path):
    loop = FakeLoop(
        segments=[segment_spec([3.0] * 48, "draft", eos=True),
                  segment_spec([3.0] * 48, "more", eos=True)],
        final_text="Result: complete sentence here. Limits: The",
    )
    agent, _ = make_agent(tmp_path, loop)
    # FakeLoop's finalizer emits exactly 24 tokens; matching final_tokens
    # makes the run look token-capped, which triggers the trim.
    out = agent.run(NFETAgentRequest(command="explain lolm", max_segments=2, final_tokens=24))
    assert out["result"]["response"] == "Result: complete sentence here."
    assert out["result"]["truncation_trimmed"] is True



def test_social_command_answers_directly(tmp_path):
    loop = FakeLoop(segments=[segment_spec([3.0] * 48, "should never be drafted")])
    agent, events = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="Hello"))

    assert out["profile"] == "social"
    assert out["ended_by"] == "social_direct"
    assert out["counters"]["segments"] == 0
    assert out["counters"]["retrieves"] == 0
    # no drafting-engine call ever happened
    assert not any("drafting engine" in c["system"] for c in loop.calls)
    # the finalizer used the friendly style, not the sectioned task style
    social_calls = [c for c in loop.calls if "friendly assistant" in c["system"]]
    assert social_calls and "Hello" in social_calls[0]["user"]
    assert out["result"]["response"].startswith("Hi there")
    assert out["proof"]["verdict"] == "social_direct_reply"
    assert any("Recognized a greeting" in p for p in out["provenance"])
    # decision recorded with profile source for the timeline/UI
    assert out["timeline"][0]["decision"]["source"] == "profile"


def test_classify_command_profiles():
    from local_ui.nfet_agent import classify_command
    assert classify_command("Hello") == "social"
    assert classify_command("hey!!") == "social"
    assert classify_command("thanks") == "social"
    assert classify_command("good morning") == "social"
    assert classify_command("How does the gate work?") == "question"
    assert classify_command("Write a plan to evaluate a 304M model") == "task"
    assert classify_command("Explain dependency inversion in LOLM") == "task"


def test_repetition_stall_finishes_early(tmp_path):
    same = "the gate arbitrates surface versus latent per dimension"
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, same),
        segment_spec([3.0] * 48, same, eos=True),  # model re-emits the draft
        segment_spec([3.0] * 48, "never reached"),
    ])
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="explain the gate", max_segments=5))
    assert out["ended_by"] == "repetition_stall"
    assert out["counters"]["segments"] == 2
    # draft holds exactly one copy, not two
    assert out["draft"].lower().count("arbitrates surface") == 1
    sources = [t["decision"]["source"] for t in out["timeline"]]
    assert "repetition" in sources
    assert any("nothing new to add" in p for p in out["provenance"])


def test_provenance_is_assembled_not_generated(tmp_path):
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, "steady opening segment"),
        segment_spec([3.0] * 36 + [6.5] * 12, "uncertain segment needs evidence"),
        segment_spec([0.8] * 48, "calm confident closing segment", drift=0.01),
    ])
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="explain the lolm latent order model"))
    # the finalizer was told to write ONLY the answer
    finalizer_calls = [c for c in loop.calls if "finalizer" in c["system"]]
    assert finalizer_calls
    assert "ONLY the answer" in finalizer_calls[0]["system"]
    assert "What I used" not in finalizer_calls[0]["system"]
    # provenance reflects the real actions: one retrieve that found notes
    assert any(p.startswith("Checked local notes — used") for p in out["provenance"])
    assert any("Decided on its own when to stop" in p for p in out["provenance"])
    # no verify ran, so provenance must not mention self-checking
    assert not any("Self-checked" in p for p in out["provenance"])


def test_irrelevant_notes_are_not_injected(tmp_path):
    # memory holds only LOLM notes; the command is about cooking
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, "first segment about pasta"),
        segment_spec([3.0] * 36 + [6.5] * 12, "uncertain pasta segment"),
        segment_spec([3.0] * 48, "closing pasta segment", eos=True),
    ])
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="how long should fresh pasta boil"))
    retrieves = [t for t in out["timeline"] if t["action"]["kind"] == "retrieve"]
    assert retrieves and retrieves[0]["action"]["added"] == 0
    # the LOLM note text never reached the drafting prompts
    drafting_calls = [c for c in loop.calls if "drafting engine" in c["system"]]
    assert not any("latent state tracking" in c["user"] for c in drafting_calls)
    assert any("none were relevant" in p for p in out["provenance"])


def test_question_profile_caps_segments(tmp_path):
    loop = FakeLoop(segments=[
        segment_spec([3.0] * 48, f"answer part {i}") for i in range(5)
    ])
    agent, _ = make_agent(tmp_path, loop)
    out = agent.run(NFETAgentRequest(command="How does the gate work?", max_segments=5))
    assert out["profile"] == "question"
    assert out["counters"]["segments"] <= 2


def test_classify_command_question_marks_across_scripts():
    from local_ui.nfet_agent import classify_command
    # fullwidth CJK, Spanish, Arabic question marks must all read as questions
    assert classify_command("LOLMモデルとは何ですか？") == "question"
    assert classify_command("¿Qué es LOLM?") == "question"
    assert classify_command("ما هو LOLM؟") == "question"
    # greetings still social; statements still task
    assert classify_command("Hello") == "social"
    assert classify_command("produce code for a snake game") == "task"
