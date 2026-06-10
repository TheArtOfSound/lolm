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

import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from local_ui import server as workspace
from local_ui.claude_reasoner import DEFAULT_CLAUDE_MODEL, ClaudeReasonerLoop
from local_ui.internet_tools import web_search
from local_ui.nfet_agent import AgentDeps, NFETAgent, NFETAgentRequest

mcp = FastMCP(
    "lolm-nfet",
    instructions=(
        "LOLM-NFET workspace: a local hybrid Transformer-SSM model whose latent "
        "telemetry (entropy, drift, gate, regime) drives an agent control loop "
        "(continue/retrieve/verify/branch/finalize), plus persistent local memory. "
        "Call load_local_model once before chat/agent/telemetry tools."
    ),
)

_AGENT: Optional[NFETAgent] = None


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


TOOLS = [
    workspace_status, load_local_model, lolm_chat, nfet_agent_run,
    memory_search, memory_add_note, memory_recent,
    identity_get, identity_add_line, goals_list, goals_add,
    journal_read, journal_write, improvement_log_tail,
]
for tool_fn in TOOLS:
    mcp.tool()(tool_fn)


if __name__ == "__main__":
    mcp.run()
