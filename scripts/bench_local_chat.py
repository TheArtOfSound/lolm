#!/usr/bin/env python3
"""Benchmark LOLM-NFET local generation speed without the browser UI."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import torch

from local_ui.server import ChatMessage, ChatRequest, generation_loop, load_model, LoadRequest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="qwen3_0_6b_smoke")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--tokens", type=int, default=24)
    parser.add_argument("--prompt", default="Say hi in one short sentence.")
    parser.add_argument("--no-graft", action="store_true")
    args = parser.parse_args()

    print(f"loading profile={args.profile} device={args.device} graft={not args.no_graft}")
    load_model(LoadRequest(profile=args.profile, device=args.device, use_graft=not args.no_graft, latent_backend="gru_debug"))
    req = ChatRequest(
        messages=[ChatMessage(role="user", content=args.prompt)],
        max_new_tokens=args.tokens,
        temperature=0.7,
        top_p=0.9,
        use_graft=not args.no_graft,
        ablation_mode="full",
    )
    start = time.perf_counter()
    token_count = 0
    final: Any = None
    for event in generation_loop(req):
        if event["event"] == "token":
            token_count += 1
            print(event["data"]["token"], end="", flush=True)
        elif event["event"] == "done":
            final = event["data"]
    elapsed = max(time.perf_counter() - start, 1e-9)
    print("\n")
    print({"tokens": token_count, "seconds": round(elapsed, 3), "tok_per_sec": round(token_count / elapsed, 3), "fast_mode": final.get("fast_mode") if final else None, "graft": final.get("use_graft") if final else None})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
