# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Serve LOLM's SELF-EVOLVED weights as an OpenAI-compatible endpoint.

The knowledge daemon promotes a cumulative LoRA adapter to runs/evolve_knowledge/live/.
`mlx_lm.server` ignores its --adapter-path (it reloads per-request from the `model` field),
so learned weights never reach answers. This shim loads base+adapter ONCE and always serves
THAT — so what LOLM learns, it actually says. Point the sovereign brain here:

    python scripts/serve_evolved.py --port 11435
    LOLM_LOCAL_API=openai LOLM_LOCAL_URL=http://127.0.0.1:11435 LOLM_LOCAL_MODEL=lolm-evolved \
      python -m local_ui.server_public_demo
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Kept in lockstep with lolm.evolve_knowledge.DEFAULT_MODEL (train and serve MUST
# use the same base). Bumped to a 3B for a stronger on-device brain; override both
# with LOLM_EVOLVE_MODEL.
DEFAULT_MODEL = os.environ.get("LOLM_EVOLVE_MODEL", "mlx-community/Qwen2.5-3B-Instruct-4bit")


class ChatBody(BaseModel):
    model: str = "lolm-evolved"
    messages: list = []
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = False


def build_app(base: str, adapter: str) -> FastAPI:
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler

    ad = adapter if adapter and Path(adapter).exists() else None
    try:
        model, tok = load(base, adapter_path=ad)     # loaded ONCE, adapter baked in
    except Exception as exc:
        # A stale adapter trained on a DIFFERENT base (e.g. after a model-size bump
        # from 0.5B to 3B) can't load — serve the clean base rather than crash. The
        # daemon will retrain a fresh adapter on the new base on its next cycle.
        print(f"[serve_evolved] adapter load failed ({exc}); serving base weights only",
              flush=True)
        model, tok = load(base)
        ad = None
    facts = 0
    st = Path(adapter or "").parent / "state.json"
    if st.exists():
        try:
            facts = json.loads(st.read_text()).get("facts_known", 0)
        except Exception:
            pass
    app = FastAPI()

    @app.get("/v1/models")
    def models():
        return {"data": [{"id": "lolm-evolved", "object": "model",
                          "adapter": bool(ad), "facts_learned": facts}]}

    @app.get("/api/tags")   # Ollama-probe compatibility so BestBrain.available() sees it
    def tags():
        return {"models": [{"name": "lolm-evolved"}]}

    @app.post("/v1/chat/completions")
    def chat(body: ChatBody):
        prompt = tok.apply_chat_template(
            [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in body.messages],
            add_generation_prompt=True,
        )
        sampler = make_sampler(temp=max(body.temperature, 0.0))
        text = generate(model, tok, prompt=prompt, max_tokens=body.max_tokens,
                        sampler=sampler, verbose=False).strip()
        return JSONResponse({
            "id": f"lolm-evolved-{int(time.time()*1000)}",
            "object": "chat.completion", "model": "lolm-evolved",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "lolm": {"served_adapter": bool(ad), "facts_learned": facts},
        })

    print(f"[serve_evolved] base={base} adapter={'ON ('+str(facts)+' facts)' if ad else 'none'}",
          flush=True)
    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default=DEFAULT_MODEL)
    p.add_argument("--adapter", default="runs/evolve_knowledge/live")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11435)
    args = p.parse_args()
    uvicorn.run(build_app(args.base, args.adapter), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
