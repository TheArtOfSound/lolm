"""LOLM-NFET Command Center server.

Runs the normal local workspace plus:
- /api/proof/compare
- /api/command/run
- /command product UI
"""

from __future__ import annotations

import os

from fastapi.responses import FileResponse

from local_ui.command_center import register_command_routes
from local_ui.proof_mode import register_proof_routes
from local_ui.server import ChatMessage, ChatRequest, MEMORY, STATIC, app, append_improvement_event, generation_loop


register_proof_routes(app, ChatRequest, generation_loop, append_improvement_event)
register_command_routes(app, ChatMessage, ChatRequest, generation_loop, MEMORY, append_improvement_event)


@app.get("/command")
def command_index():
    return FileResponse(str(STATIC / "command.html"))


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host=host, port=port)
