#!/usr/bin/env python3
"""Proof Mode: compare base model output against LOLM-NFET output."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

from local_ui.server import ChatMessage, ChatRequest, LoadRequest, generation_loop, load_model


def collect(label: str, req: ChatRequest, quiet: bool = False) -> Dict[str, Any]:
    start = time.perf_counter()
    final = None
    text = ""
    tokens = 0
    if not quiet:
        print(f"\n=== RUNNING {label} ===", flush=True)
    for event in generation_loop(req):
        if event["event"] == "start" and not quiet:
            data = event.get("data", {})
            print(f"[{label}] start profile={data.get('profile')} graft={data.get('use_graft')} fast={data.get('fast_mode')} engine={data.get('latent_backend')}", flush=True)
        elif event["event"] == "token":
            tok = event["data"].get("token", "")
            text += tok
            tokens += 1
            if not quiet:
                print(tok, end="", flush=True)
        elif event["event"] == "done":
            final = event["data"]
        elif event["event"] == "error":
            raise RuntimeError(event.get("data", {}).get("error", "generation failed"))
    elapsed = max(time.perf_counter() - start, 1e-9)
    if final is None:
        final = {"response": text, "tokens": tokens}
    final["seconds"] = elapsed
    final["tok_per_sec"] = tokens / elapsed
    if not quiet:
        print(f"\n[{label}] done tokens={tokens} seconds={elapsed:.2f} tok/s={tokens / elapsed:.3f}", flush=True)
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
        "base_seconds": round(base.get("seconds", 0), 3),
        "lolm_seconds": round(lolm.get("seconds", 0), 3),
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
    parser.add_argument("--tokens", type=int, default=12)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    print(f"Loading {args.profile} on {args.device}. This can take 10-90 seconds on first run.", flush=True)
    load_model(LoadRequest(profile=args.profile, device=args.device, use_graft=True, latent_backend="gru_debug"))
    print("Model loaded. Running base vs LOLM proof comparison.", flush=True)

    messages = [ChatMessage(role="user", content=args.prompt)]
    base = collect("BASE MODEL", ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=0.7, top_p=0.9, use_graft=False), quiet=args.quiet)
    lolm = collect("LOLM-NFET", ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=0.7, top_p=0.9, use_graft=True), quiet=args.quiet)
    diff = summarize(base, lolm)

    print("\n=== BASE MODEL FINAL ===\n")
    print(base.get("response", ""))
    print("\n=== LOLM-NFET FINAL ===\n")
    print(lolm.get("response", ""))
    print("\n=== PROOF SUMMARY ===\n")
    print(json.dumps(diff, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
