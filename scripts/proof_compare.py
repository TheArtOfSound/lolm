#!/usr/bin/env python3
"""Proof Mode: compare base model output against LOLM-NFET output."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

from local_ui.server import ChatMessage, ChatRequest, LoadRequest, generation_loop, load_model


def collect(req: ChatRequest) -> Dict[str, Any]:
    start = time.perf_counter()
    final = None
    text = ""
    tokens = 0
    for event in generation_loop(req):
        if event["event"] == "token":
            text += event["data"].get("token", "")
            tokens += 1
        elif event["event"] == "done":
            final = event["data"]
    elapsed = max(time.perf_counter() - start, 1e-9)
    if final is None:
        final = {"response": text, "tokens": tokens}
    final["seconds"] = elapsed
    final["tok_per_sec"] = tokens / elapsed
    return final


def summarize(base: Dict[str, Any], lolm: Dict[str, Any]) -> Dict[str, Any]:
    b = (base.get("response") or "").strip()
    l = (lolm.get("response") or "").strip()
    bs = set(b.lower().split())
    ls = set(l.lower().split())
    similarity = len(bs & ls) / max(len(bs | ls), 1)
    summary = lolm.get("summary", {}) or {}
    latent = summary.get("avg_latent_share")
    control = summary.get("last_control")
    if b == l:
        plain = "No visible difference. LOLM/NFET ran, but did not change the user-facing answer."
    elif latent is None:
        plain = "The answers changed, but no latent-share summary was recorded."
    else:
        plain = f"LOLM/NFET changed the answer with about {round(latent * 100)}% average latent contribution. Final NFET control: {control}."
    return {
        "changed_text": b != l,
        "word_similarity": round(similarity, 3),
        "base_tok_per_sec": round(base.get("tok_per_sec", 0), 3),
        "lolm_tok_per_sec": round(lolm.get("tok_per_sec", 0), 3),
        "avg_gate": summary.get("avg_gate"),
        "avg_latent_share": latent,
        "last_control": control,
        "plain": plain,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?", default="Explain why LOLM-NFET should feel different from a normal local chatbot.")
    parser.add_argument("--profile", default="qwen3_0_6b_smoke")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--tokens", type=int, default=32)
    args = parser.parse_args()

    load_model(LoadRequest(profile=args.profile, device=args.device, use_graft=True, latent_backend="gru_debug"))
    messages = [ChatMessage(role="user", content=args.prompt)]
    base = collect(ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=0.7, top_p=0.9, use_graft=False))
    lolm = collect(ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=0.7, top_p=0.9, use_graft=True))
    diff = summarize(base, lolm)

    print("\n=== BASE MODEL ===\n")
    print(base.get("response", ""))
    print("\n=== LOLM-NFET ===\n")
    print(lolm.get("response", ""))
    print("\n=== PROOF SUMMARY ===\n")
    print(json.dumps(diff, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
