"""MCP server for the LOLM-NFET workspace.

Exposes the workspace — the NFET agent, the local model with latent
telemetry, and the persistent memory — as Model Context Protocol tools, so
any MCP client (Claude Code, Claude Desktop, an Agent SDK harness) can drive
it. This is the open-platform face of the project: a frontier agent gets a
local latent-telemetry co-processor, a private memory, and a self-improving
control loop as plug-in tools.

Run (stdio):
    PYTHONPATH=. python local_ui/mcp_server.py

Claude Code registration (.mcp.json at the repo root):
    {
      "mcpServers": {
        "lolm-nfet": {
          "command": ".venv/bin/python",
          "args": ["local_ui/mcp_server.py"],
          "env": {"PYTHONPATH": "."}
        }
      }
    }

The local model is lazy-loaded: memory and log tools work instantly;
`load_local_model` pulls the backbone (downloads on first use) and arms the
telemetry/agent tools.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any, Dict, List, Optional

from local_ui import byok
byok.load_into_env()   # BYOK: panel-saved keys (ANTHROPIC etc.) reach this entrypoint too

from mcp.server.fastmcp import FastMCP

from local_ui import server as workspace
from local_ui.claude_reasoner import (
    DEFAULT_CLAUDE_MODEL,
    ClaudeReasonerLoop,
    telemetry_traces_from_text,
)
from local_ui.internet_tools import web_search
from local_ui.nfet_agent import AgentDeps, NFETAgent, NFETAgentRequest
from lolm.nfet_policy import (
    CONTROL_CONTINUE,
    CONTROL_FINALIZE,
    ControlDecision,
    NFETControlPolicy,
    TelemetryFrame,
    softmax,
)

mcp = FastMCP(
    "lolm-nfet",
    instructions=(
        "LOLM-NFET workspace: a local hybrid Transformer-SSM model whose latent "
        "telemetry (entropy, drift, gate, regime) drives an agent control loop "
        "(continue/retrieve/verify/branch/finalize), plus persistent local memory. "
        "Call load_local_model once before chat/agent/telemetry tools. Frontier "
        "clients should call nfet_monitor_text with reset=true and checkpoint=plan "
        "on their first plan, then replay later work and act on each control "
        "decision. Submit the final checked result with checkpoint=result and "
        "verified=true."
    ),
)

_AGENT: Optional[NFETAgent] = None
_MONITOR_POLICY: Optional[NFETControlPolicy] = None


def _agent() -> NFETAgent:
    global _AGENT
    if _AGENT is None:
        _AGENT = NFETAgent(AgentDeps(
            memory=workspace.MEMORY,
            ChatMessage=workspace.ChatMessage,
            ChatRequest=workspace.ChatRequest,
            generation_loop=workspace.generation_loop,
            append_event=workspace.append_improvement_event,
            head_trained_fn=lambda: workspace.STATE.head_trained,
            web_search=web_search,
            frontier_loop=ClaudeReasonerLoop(lambda: workspace.STATE, model=DEFAULT_CLAUDE_MODEL),
        ))
    return _AGENT


# ---------------------------------------------------------------------------
# Workspace / model
# ---------------------------------------------------------------------------

def workspace_status() -> Dict[str, Any]:
    """Current workspace state: loaded model, graft backend, trained head, history."""
    return workspace.status()


def load_local_model(profile: str = "qwen3_0_6b_smoke", device: str = "auto",
                     graft_checkpoint: str = "", latent_backend: str = "gru_debug") -> Dict[str, Any]:
    """Load the local backbone + LOLM-NFET graft (downloads the model on first use).

    Pass graft_checkpoint=runs/nfet_controller/bootstrap_qwen06b.pt to arm the
    trained control head so it can override the heuristic policy.
    """
    req = workspace.LoadRequest(
        profile=profile, device=device,
        graft_checkpoint=graft_checkpoint or None,
        latent_backend=latent_backend,
    )
    return workspace.load_model(req)


def lolm_chat(message: str, max_new_tokens: int = 128, temperature: float = 0.7) -> Dict[str, Any]:
    """Chat with the local model; returns the reply plus NFET telemetry summary."""
    req = workspace.ChatRequest(
        messages=[workspace.ChatMessage(role="user", content=message)],
        max_new_tokens=max_new_tokens, temperature=temperature,
    )
    result = workspace.chat(req)
    return {
        "response": result.get("response"),
        "tokens": result.get("tokens"),
        "nfet": result.get("nfet"),
        "summary": result.get("summary"),
        "id": result.get("id"),
    }


def nfet_agent_run(command: str, reasoner: str = "local", allow_web: bool = False,
                   max_segments: int = 6, segment_tokens: int = 48,
                   final_tokens: int = 200) -> Dict[str, Any]:
    """Run the NFET agent: latent telemetry drives retrieve/verify/branch/finalize.

    reasoner='local' uses the local model end to end; reasoner='claude' lets
    Claude generate while the local graft monitors and controls (needs
    ANTHROPIC_API_KEY). Returns the answer, the control timeline, and the
    proof receipt.
    """
    result = _agent().run(NFETAgentRequest(
        command=command, reasoner=reasoner, allow_web=allow_web,
        max_segments=max_segments, segment_tokens=segment_tokens,
        final_tokens=final_tokens,
    ))
    if "error" in result:
        return result
    return {
        "response": result["result"].get("response"),
        "reasoner": result["reasoner"],
        "head_trained": result["head_trained"],
        "timeline": [
            {
                "segment": t["segment"],
                "decision": t["decision"]["label"],
                "source": t["decision"]["source"],
                "reason": t["decision"]["reason"],
                "action": t.get("action", {}),
            }
            for t in result["timeline"]
        ],
        "counters": result["counters"],
        "ended_by": result["ended_by"],
        "proof": result["proof"],
        "evidence_count": len(result.get("evidence", [])),
    }


def _aggregate_control_logits(traces: List[Dict[str, Any]],
                              tail: int = 32) -> Optional[List[float]]:
    """Average token probabilities so one extreme terminal logit cannot dominate."""
    rows = [trace.get("control_logits") for trace in traces]
    rows = [row for row in rows if isinstance(row, list) and len(row) == 5]
    if not rows:
        return None
    rows = rows[-max(1, tail):]
    probabilities = [softmax([float(value) for value in row]) for row in rows]
    mean_probabilities = [
        sum(row[i] for row in probabilities) / len(probabilities) for i in range(5)
    ]
    # NFETControlPolicy accepts logits and applies softmax. Log probabilities
    # preserve the averaged distribution under that second softmax.
    return [math.log(max(probability, 1e-12)) for probability in mean_probabilities]


def _guard_monitor_decision(decision: ControlDecision, policy: NFETControlPolicy,
                            checkpoint: str, verified: bool) -> ControlDecision:
    """Require stateful telemetry support for disruptive pointwise-head actions."""
    z = decision.zscores
    cfg = policy.cfg
    unsupported = ""
    if decision.source == "head":
        if decision.label == "retrieve" and z.get("entropy", 0.0) < cfg.entropy_spike_z:
            unsupported = "retrieve lacked a sustained entropy spike"
        elif decision.label == "verify" and (
            z.get("drift", 0.0) < cfg.drift_spike_z
            or z.get("entropy", 0.0) < cfg.verify_entropy_z
        ):
            unsupported = "verify lacked the required drift and uncertainty"
        elif decision.label == "branch" and (
            z.get("regime", 0.0) > cfg.regime_stall_z
            or z.get("entropy", 0.0) < cfg.branch_entropy_z
        ):
            unsupported = "branch lacked a supported regime stall"

    if unsupported:
        decision = ControlDecision(
            CONTROL_CONTINUE,
            "continue",
            "telemetry_guard",
            f"{unsupported}; continuing instead of accepting a pointwise-head override",
            z,
            head_probs=decision.head_probs,
            step=decision.step,
        )

    if decision.control == CONTROL_FINALIZE and not (checkpoint == "result" and verified):
        return ControlDecision(
            CONTROL_CONTINUE,
            "continue",
            "completion_guard",
            "finalize requires checkpoint=result and verified=true",
            z,
            head_probs=decision.head_probs,
            step=decision.step,
        )

    if checkpoint == "result" and verified and decision.control == CONTROL_CONTINUE:
        return ControlDecision(
            CONTROL_FINALIZE,
            "finalize",
            "verified_result",
            "Codex reported normal completion checks passed and telemetry raised no supported intervention",
            z,
            head_probs=decision.head_probs,
            step=decision.step,
        )
    return decision


def nfet_monitor_text(text: str, reset: bool = False, max_tokens: int = 1024,
                      checkpoint: str = "work", verified: bool = False) -> Dict[str, Any]:
    """Replay external text through LOLM and return an NFET control decision.

    This is the bridge for frontier clients such as Codex: submit a plan,
    draft, or result at a checkpoint, then use the returned action to decide
    whether to continue, retrieve evidence, verify, branch, or finalize.
    Set reset=True and checkpoint="plan" on the first checkpoint of a new task.
    Use checkpoint="result", verified=True only after normal completion checks.
    """
    global _MONITOR_POLICY
    text = text.strip()
    if not text:
        return {"error": "text must not be empty"}
    checkpoint = checkpoint.strip().lower()
    if checkpoint not in {"plan", "work", "result"}:
        return {"error": "checkpoint must be one of: plan, work, result"}
    if verified and checkpoint != "result":
        return {"error": "verified=true is only valid for checkpoint=result"}
    if workspace.STATE.backbone is None or workspace.STATE.graft is None:
        return {
            "error": "LOLM model is not loaded",
            "next": (
                "Call load_local_model first; on this Mac use profile="
                "qwen3_4b_lab, device=mps, graft_checkpoint="
                "runs/nfet_controller/live_qwen4b.pt, latent_backend=gru_debug"
            ),
        }

    if reset or _MONITOR_POLICY is None:
        _MONITOR_POLICY = NFETControlPolicy()

    token_limit = max(32, min(int(max_tokens), 4096))
    traces = telemetry_traces_from_text(
        workspace.STATE.backbone,
        workspace.STATE.graft,
        text,
        max_tokens=token_limit,
    )
    frames = [
        TelemetryFrame.from_trace(trace, step=index + 1)
        for index, trace in enumerate(traces)
    ]
    if not frames:
        return {"error": "LOLM produced no telemetry frames"}

    _MONITOR_POLICY.observe_all(frames)
    control_logits = _aggregate_control_logits(traces)
    previous_last_action_at = _MONITOR_POLICY.last_action_at
    raw_decision = _MONITOR_POLICY.decide(
        control_logits=control_logits,
        head_trained=workspace.STATE.head_trained,
    )
    decision = _guard_monitor_decision(
        raw_decision, _MONITOR_POLICY, checkpoint=checkpoint, verified=verified,
    )
    if raw_decision.control != CONTROL_CONTINUE and decision.control == CONTROL_CONTINUE:
        _MONITOR_POLICY.last_action_at = previous_last_action_at
    elif raw_decision.control == CONTROL_CONTINUE and decision.control != CONTROL_CONTINUE:
        _MONITOR_POLICY.last_action_at = _MONITOR_POLICY.frames_seen

    def mean(key: str) -> float:
        values = [float(trace[key]) for trace in traces if trace.get(key) is not None]
        return round(sum(values) / len(values), 6) if values else 0.0

    action_guidance = {
        "continue": "Proceed with the current approach and monitor again at the next checkpoint.",
        "retrieve": "Gather missing repository, documentation, web, or memory evidence before proceeding.",
        "verify": "Run targeted tests or inspect primary evidence before trusting the draft.",
        "branch": "Develop and compare at least one materially different approach.",
        "finalize": "The trajectory is stable enough to prepare the user-facing result.",
    }
    telemetry = {
        "avg_entropy": mean("graft_entropy"),
        "avg_hidden_drift": mean("hidden_drift"),
        "avg_gate": mean("gate_mean"),
        "avg_regime_entropy": mean("regime_entropy"),
    }
    receipt_id = f"monitor-{time.time_ns()}"
    receipt = {
        "type": "monitor",
        "id": receipt_id,
        "timestamp": time.time(),
        "profile": workspace.STATE.profile,
        "checkpoint": checkpoint,
        "verified": verified,
        "reset": reset,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_chars": len(text),
        "observed_tokens": len(frames),
        "monitor_frames_seen": _MONITOR_POLICY.frames_seen,
        "head_trained": workspace.STATE.head_trained,
        "decision": decision.to_dict(),
        "telemetry": telemetry,
    }
    workspace.append_improvement_event(receipt)
    return {
        "receipt_id": receipt_id,
        "profile": workspace.STATE.profile,
        "checkpoint": checkpoint,
        "verified": verified,
        "observed_tokens": len(frames),
        "monitor_frames_seen": _MONITOR_POLICY.frames_seen,
        "head_trained": workspace.STATE.head_trained,
        "decision": decision.to_dict(),
        "codex_action": action_guidance[decision.label],
        "telemetry": telemetry,
    }


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def memory_search(query: str, limit: int = 10) -> Dict[str, Any]:
    """Keyword-search the workspace's persistent local memory notes."""
    return {"items": workspace.MEMORY.search_notes(query, limit=limit)}


def memory_add_note(text: str, tag: str = "note", importance: int = 3) -> Dict[str, Any]:
    """Save a durable note to the workspace memory."""
    return {"saved": True, "id": workspace.MEMORY.append_note(text, tag=tag, importance=importance)}


def memory_recent(limit: int = 10) -> Dict[str, Any]:
    """Most recent workspace memory notes."""
    return {"items": workspace.MEMORY.recent_notes(limit=limit)}


def identity_get() -> Dict[str, Any]:
    """Read the workspace's durable identity document."""
    return {"identity": workspace.MEMORY.read_identity()}


def identity_add_line(line: str) -> Dict[str, Any]:
    """Append one durable fact to the workspace identity document."""
    workspace.MEMORY.append_identity_line(line)
    return {"saved": True}


def goals_list() -> Dict[str, Any]:
    """List the workspace's explicit goals."""
    return {"items": workspace.MEMORY.get_goals()}


def goals_add(title: str, why: str = "", priority: int = 3) -> Dict[str, Any]:
    """Add an active goal to the workspace."""
    return {"saved": True, "id": workspace.MEMORY.add_goal(title, why=why, priority=priority)}


def journal_read(max_chars: int = 4000) -> Dict[str, Any]:
    """Read the tail of the workspace's running journal."""
    return {"journal": workspace.MEMORY.read_journal(max_chars=max_chars)}


def journal_write(markdown: str) -> Dict[str, Any]:
    """Append a markdown entry to the workspace journal."""
    workspace.MEMORY.append_journal(markdown)
    return {"saved": True}


def improvement_log_tail(limit: int = 20, event_type: str = "") -> Dict[str, Any]:
    """Tail the improvement log (every chat/agent run with telemetry and proofs).

    This is the flywheel data that trains the NFET control head.
    """
    path = workspace.IMPROVEMENT_LOG
    if not path.exists():
        return {"items": [], "path": str(path)}
    items: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event_type and event.get("type") != event_type:
            continue
        items.append({k: v for k, v in event.items() if k not in ("trace", "frames")})
    return {"items": items[-limit:], "path": str(path), "total": len(items)}


def _nfet_observer_frames(text: str) -> List[Dict[str, Any]]:
    """Best-effort independent-observer telemetry: re-read Claude's text through
    the local backbone+graft. Returns [] when no local model is loaded — the
    harness then proceeds on Claude's self-confidence alone (honestly recorded).
    """
    try:
        return telemetry_traces_from_text(
            workspace.STATE.backbone, workspace.STATE.graft, text)
    except Exception:
        return []


def claude_receipt(task: str, answer: str, self_confidence: float,
                   action_kind: str = "answer") -> Dict[str, Any]:
    """Wrap a Claude Code turn in the full LOLM loop and return a sealed receipt.

    THIS is "Claude does what LOLM does": Claude is the reasoner, and this runs
    the discipline layer around it — deterministic verifiers (catches wrong
    numbers), risk profiling, the uncertainty-gated autonomy decision
    (act/gather/escalate by risk tier, with a hard human gate on
    payment/send/delete/deploy), a hash-chained receipt, and the
    verified-outcome flywheel that calibrates Claude's confidence over time.

    ``self_confidence`` is Claude's own P(correct) in [0,1] for this turn.
    ``action_kind`` is the real action the turn takes: answer / advise / draft /
    edit / write_file / run_code / post / publish / send / email / payment /
    delete / deploy. It sets the risk tier. If a local model is loaded, its
    latent telemetry re-reads the answer as an INDEPENDENT second opinion and
    can only raise caution (never grant confidence).
    """
    from local_ui.claude_harness import claude_turn_receipt
    frames = _nfet_observer_frames(answer)
    receipt = claude_turn_receipt(task, answer, self_confidence,
                                  action_kind=action_kind, nfet_frames=frames)
    # Trim the heavy standard-receipt layers for transport; the Claude-brain
    # layers are what the client acts on.
    return {
        "status_color": receipt["status_color"],
        "autonomy": receipt["autonomy"],
        "second_opinion": receipt["second_opinion"],
        "assessment": receipt["assessment"],
        "hard_human_gated": receipt["hard_human_gated"],
        "chain": receipt["chain"],
        "prompt_sha256": receipt.get("prompt", {}).get("sha256"),
    }


def claude_gate(action_kind: str, self_confidence: float = 0.85,
                task: str = "") -> Dict[str, Any]:
    """Pre-action gate: decide act/gather/escalate for an action BEFORE running it.

    No receipt, no flywheel write — the cheap check the PreToolUse hook uses.
    Honours the hard human gate (payment/send/delete/deploy always escalate).
    """
    from local_ui.claude_harness import gate_only
    return gate_only(action_kind, self_confidence=self_confidence, task=task,
                     nfet_frames=_nfet_observer_frames(task) if task else None)


def claude_flywheel() -> Dict[str, Any]:
    """Claude's verified-outcome track record + recent hash-chained receipts.

    The flywheel is fit ONLY on deterministically-checkable outcomes (a wrong
    number is an objective miss) — never on self-report. Until 20 records it is
    uncalibrated and the gate uses a conservative prior.
    """
    from local_ui.claude_harness import flywheel, ledger_tail
    return {"flywheel": flywheel().stats(), "recent_receipts": ledger_tail(10)}


TOOLS = [
    workspace_status, load_local_model, lolm_chat, nfet_agent_run,
    nfet_monitor_text,
    claude_receipt, claude_gate, claude_flywheel,
    memory_search, memory_add_note, memory_recent,
    identity_get, identity_add_line, goals_list, goals_add,
    journal_read, journal_write, improvement_log_tail,
]
for tool_fn in TOOLS:
    mcp.tool()(tool_fn)


if __name__ == "__main__":
    mcp.run()
