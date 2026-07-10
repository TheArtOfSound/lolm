"""LOLM-NFET Action Orchestrator server.

Run this launcher for the full product stack:
- lab UI
- command UI
- proof comparison
- command center
- action orchestrator
- self tick
"""

from __future__ import annotations

import os

from local_ui import byok
byok.load_into_env()   # BYOK: panel-saved keys (ANTHROPIC etc.) reach this entrypoint too

from fastapi.responses import FileResponse

from local_ui.action_orchestrator import ActionOrchestrator, register_agent_routes
from local_ui.claude_reasoner import DEFAULT_CLAUDE_MODEL, ClaudeReasonerLoop
from local_ui.command_center import register_command_routes
from local_ui.internet_tools import fetch_url, web_search
from local_ui.nfet_agent import AgentDeps, NFETAgent, register_nfet_agent_routes
from local_ui.proof_mode import register_proof_routes
from local_ui.self_tick import SelfTickEngine, register_self_tick_routes
from local_ui.server import STATE, ChatMessage, ChatRequest, DATA_DIR, MEMORY, STATIC, app, append_improvement_event, generation_loop

register_proof_routes(app, ChatRequest, generation_loop, append_improvement_event)
register_command_routes(app, ChatMessage, ChatRequest, generation_loop, MEMORY, append_improvement_event)
register_agent_routes(app, ActionOrchestrator(MEMORY, ChatMessage, ChatRequest, generation_loop, append_improvement_event))
register_self_tick_routes(app, SelfTickEngine(DATA_DIR, MEMORY, ChatMessage, ChatRequest, generation_loop, append_improvement_event))
register_nfet_agent_routes(app, NFETAgent(AgentDeps(
    memory=MEMORY,
    ChatMessage=ChatMessage,
    ChatRequest=ChatRequest,
    generation_loop=generation_loop,
    append_event=append_improvement_event,
    head_trained_fn=lambda: STATE.head_trained,
    web_search=web_search,
    fetch_url=fetch_url,
    frontier_loop=ClaudeReasonerLoop(
        lambda: STATE,
        model=os.environ.get("LOLM_CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
    ),
)))


@app.get("/command")
def command_index():
    return FileResponse(str(STATIC / "command.html"))


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host=host, port=port)
