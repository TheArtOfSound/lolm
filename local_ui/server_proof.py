"""LOLM-NFET local server with Proof Mode enabled.

Run this instead of local_ui/server.py when you want the normal UI plus
/api/proof/compare.
"""

from __future__ import annotations

import os

from local_ui.proof_mode import register_proof_routes
from local_ui.server import ChatRequest, app, append_improvement_event, generation_loop


register_proof_routes(app, ChatRequest, generation_loop, append_improvement_event)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host=host, port=port)
