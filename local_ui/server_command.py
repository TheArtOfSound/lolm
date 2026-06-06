"""LOLM-NFET Command Center server.

Runs the normal local workspace plus:
- /api/proof/compare
- /api/command/run
- /api/self/tick
- /command product UI
"""

from __future__ import annotations

import os

from fastapi.responses import FileResponse

from local_ui.command_center import register_command_routes
from local_ui.proof_mode import register_proof_routes
from local_ui.self_tick import SelfTickEngine, register_self_tick_routes
from local_ui.server import ChatMessage, ChatRequest, DATA_DIR, MEMORY, STATIC, app, append_improvement_event, generation_loop


register_proof_routes(app, ChatRequest, generation_loop, append_improvement_event)
register_command_routes(app, ChatMessage, ChatRequest, generation_loop, MEMORY, append_improvement_event)
SELF_TICK = SelfTickEngine(DATA_DIR, MEMORY, ChatMessage, ChatRequest, generation_loop, append_improvement_event)
register_self_tick_routes(app, SELF_TICK)


@app.get("/command")
def command_index():
    return FileResponse(str(STATIC / "command.html"))


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host=host, port=port)
