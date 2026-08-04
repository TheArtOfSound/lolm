#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Serve LOLM-Core evolved weights with canary routing.

Priority for adapters:
  1) runs/evolution/live (gated product evolution plane)
  2) runs/evolve_knowledge/live (legacy fact LoRA)
  3) base model only

Canary: live/manifest.json canary_pct routes a fraction of requests to the
candidate adapter; the rest use previous_known_good or base.

    python scripts/serve_evolved.py --port 11435
    LOLM_LOCAL_API=openai LOLM_LOCAL_URL=http://127.0.0.1:11435 LOLM_LOCAL_MODEL=lolm-evolved
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = os.environ.get("LOLM_EVOLVE_MODEL", "mlx-community/Qwen2.5-3B-Instruct-4bit")


class ChatBody(BaseModel):
    model: str = "lolm-evolved"
    messages: list = []
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = False


def _adapter_ok(path: Path) -> bool:
    return (path / "adapters.safetensors").exists() and (path / "adapters.safetensors").stat().st_size > 64


def _is_dry_run_adapter(path: Path) -> bool:
    if not path.exists():
        return True
    cfg = path / "adapter_config.json"
    if cfg.exists():
        try:
            if json.loads(cfg.read_text()).get("dry_run"):
                return True
        except Exception:
            pass
    af = path / "adapters.safetensors"
    if af.exists() and af.stat().st_size < 8192:
        try:
            json.loads(af.read_text())
            return True
        except Exception:
            pass
    return False


def resolve_default_adapter(repo: Path, explicit: str = "") -> Tuple[str, Dict[str, Any]]:
    """Pick best real adapter path (skip dry-run stubs for serving)."""
    if explicit:
        p = Path(explicit)
        if _adapter_ok(p) and not _is_dry_run_adapter(p):
            return str(p), {"source": "cli", "served": "explicit"}

    evo_live = repo / "runs" / "evolution" / "live" / "adapter"
    evo_prev = repo / "runs" / "evolution" / "previous" / "adapter"
    know = repo / "runs" / "evolve_knowledge" / "live"

    # Prefer real evolution adapters via canary helper
    try:
        from lolm.evolution.canary import select_adapter
        path, meta = select_adapter(repo, request_id=f"boot-{time.time()}")
        if path and _adapter_ok(Path(path)) and not _is_dry_run_adapter(Path(path)):
            meta["source"] = "evolution"
            return path, meta
    except Exception:
        pass

    for label, p in (
        ("evolution_live", evo_live),
        ("evolution_previous", evo_prev),
        ("knowledge_live", know),
    ):
        if _adapter_ok(p) and not _is_dry_run_adapter(p):
            return str(p), {"source": label, "served": label}
    return "", {"source": "base", "served": "base"}


def build_app(base: str, adapter: str, repo: Path) -> FastAPI:
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler

    # Load up to two adapters for canary: primary (resolved) + alternate
    models: Dict[str, Any] = {}
    tokens: Dict[str, Any] = {}

    def _load(label: str, ad: Optional[str]) -> None:
        try:
            if ad and Path(ad).exists() and not _is_dry_run_adapter(Path(ad)):
                m, t = load(base, adapter_path=ad)
                models[label] = m
                tokens[label] = t
                print(f"[serve_evolved] loaded {label} adapter={ad}", flush=True)
            else:
                m, t = load(base)
                models[label] = m
                tokens[label] = t
                print(f"[serve_evolved] loaded {label} base-only", flush=True)
        except Exception as exc:
            print(f"[serve_evolved] load {label} failed ({exc}); base only", flush=True)
            m, t = load(base)
            models[label] = m
            tokens[label] = t

    primary_path, primary_meta = resolve_default_adapter(repo, adapter)
    _load("primary", primary_path or None)

    # Secondary: previous known good or knowledge for canary incumbent
    evo_prev = repo / "runs" / "evolution" / "previous" / "adapter"
    know = repo / "runs" / "evolve_knowledge" / "live"
    alt = ""
    if _adapter_ok(evo_prev) and not _is_dry_run_adapter(evo_prev):
        alt = str(evo_prev)
    elif _adapter_ok(know) and not _is_dry_run_adapter(know):
        alt = str(know)
    if alt and alt != primary_path:
        _load("incumbent", alt)
    else:
        models["incumbent"] = models["primary"]
        tokens["incumbent"] = tokens["primary"]

    # Canary candidate = evolution live if real
    evo_live = repo / "runs" / "evolution" / "live" / "adapter"
    if (
        _adapter_ok(evo_live)
        and not _is_dry_run_adapter(evo_live)
        and str(evo_live) != primary_path
        and str(evo_live) != alt
    ):
        _load("canary", str(evo_live))
    else:
        models["canary"] = models["primary"]
        tokens["canary"] = tokens["primary"]

    facts = 0
    for st in (
        Path(primary_path or "").parent / "state.json",
        repo / "runs" / "evolve_knowledge" / "state.json",
        repo / "runs" / "evolution" / "live" / "manifest.json",
    ):
        if st.exists():
            try:
                d = json.loads(st.read_text())
                facts = max(facts, int(d.get("facts_known") or d.get("sft_examples") or 0))
            except Exception:
                pass

    app = FastAPI()

    def _pick_slot(request_id: str) -> Tuple[str, Dict[str, Any]]:
        try:
            from lolm.evolution.canary import select_adapter
            path, meta = select_adapter(repo, request_id=request_id)
            if path and str(Path(path).resolve()) == str(evo_live.resolve()):
                return "canary", meta
            if path and alt and str(Path(path).resolve()) == str(Path(alt).resolve()):
                return "incumbent", meta
            if path and primary_path and str(Path(path).resolve()) == str(Path(primary_path).resolve()):
                return "primary", meta
            return "primary", meta
        except Exception:
            return "primary", {"served": "primary"}

    @app.get("/v1/models")
    def models_ep():
        man = {}
        mp = repo / "runs" / "evolution" / "live" / "manifest.json"
        if mp.exists():
            try:
                man = json.loads(mp.read_text())
            except Exception:
                pass
        return {
            "data": [{
                "id": "lolm-evolved",
                "object": "model",
                "adapter": bool(primary_path),
                "facts_learned": facts,
                "evolution": {
                    "canary_pct": man.get("canary_pct"),
                    "decision": man.get("decision"),
                    "model_version": man.get("model_version"),
                    "primary": primary_meta,
                },
            }],
        }

    @app.get("/api/tags")
    def tags():
        return {"models": [{"name": "lolm-evolved"}]}

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "primary_adapter": primary_path or None,
            "slots": list(models.keys()),
            "meta": primary_meta,
        }

    @app.post("/v1/chat/completions")
    async def chat(body: ChatBody, request: Request):
        rid = request.headers.get("x-request-id") or f"{time.time()}-{id(body)}"
        slot, meta = _pick_slot(rid)
        model = models.get(slot) or models["primary"]
        tok = tokens.get(slot) or tokens["primary"]
        prompt = tok.apply_chat_template(
            [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in body.messages],
            add_generation_prompt=True,
        )
        sampler = make_sampler(temp=max(body.temperature, 0.0))
        text = generate(
            model, tok, prompt=prompt, max_tokens=body.max_tokens,
            sampler=sampler, verbose=False,
        ).strip()
        return JSONResponse({
            "id": f"lolm-evolved-{int(time.time()*1000)}",
            "object": "chat.completion",
            "model": "lolm-evolved",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }],
            "lolm": {
                "served_adapter": bool(primary_path),
                "slot": slot,
                "canary": meta,
                "facts_learned": facts,
            },
        })

    print(
        f"[serve_evolved] base={base} primary={primary_path or 'none'} meta={primary_meta}",
        flush=True,
    )
    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default=DEFAULT_MODEL)
    p.add_argument(
        "--adapter",
        default="",
        help="Optional explicit adapter dir; default prefers runs/evolution/live then knowledge",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11435)
    p.add_argument("--repo", type=Path, default=REPO)
    args = p.parse_args()
    uvicorn.run(
        build_app(args.base, args.adapter, Path(args.repo)),
        host=args.host,
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
