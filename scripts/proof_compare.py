#!/usr/bin/env python3
"""Proof Mode: compare base model output against LOLM-NFET output.

A changed answer is not automatically a better answer. This script flags
truncation, generic output, speed cost, and whether the LOLM/NFET path produced
a meaningful user-facing improvement.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

import torch

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
    final["hit_token_limit"] = int(final.get("tokens", tokens) or tokens) >= int(req.max_new_tokens)
    if not quiet:
        print(f"\n[{label}] done tokens={tokens} seconds={elapsed:.2f} tok/s={tokens / elapsed:.3f}", flush=True)
    return final


def quality_flags(text: str) -> Dict[str, bool]:
    stripped = (text or "").strip()
    lower = stripped.lower()
    return {
        "empty": not stripped,
        "very_short": len(stripped.split()) < 18,
        "generic": any(p in lower for p in ["designed to", "tailored", "context-aware", "unlike a standard", "more personal"]),
        "trails_off": not stripped.endswith((".", "!", "?", ")", '"')),
        "mentions_memory": any(p in lower for p in ["memory", "remember", "journal", "goal", "context"]),
        "mentions_tools": any(p in lower for p in ["tool", "browser", "search", "retrieve", "verify"]),
    }


def verdict(base: Dict[str, Any], lolm: Dict[str, Any], similarity: float, latent: Any) -> str:
    btxt = base.get("response") or ""
    ltxt = lolm.get("response") or ""
    bf = quality_flags(btxt)
    lf = quality_flags(ltxt)
    if base.get("hit_token_limit") or lolm.get("hit_token_limit") or bf["trails_off"] or lf["trails_off"]:
        return "invalid_due_to_truncation"
    if not ltxt.strip():
        return "failed_lolm_empty"
    if btxt.strip() == ltxt.strip():
        return "no_visible_difference"
    if lf["generic"] and not (lf["mentions_memory"] or lf["mentions_tools"]):
        return "changed_but_not_better"
    if latent is not None and float(latent) > 0.15 and similarity < 0.75 and (lf["mentions_memory"] or lf["mentions_tools"]):
        return "meaningful_improvement_candidate"
    return "changed_but_unproven"


def summarize(base: Dict[str, Any], lolm: Dict[str, Any]) -> Dict[str, Any]:
    b = (base.get("response") or "").strip()
    l = (lolm.get("response") or "").strip()
    bs = set(b.lower().split())
    ls = set(l.lower().split())
    similarity = len(bs & ls) / max(len(bs | ls), 1)
    summary = lolm.get("summary", {}) or {}
    latent = summary.get("avg_latent_share")
    control = summary.get("last_control")
    v = verdict(base, lolm, similarity, latent)
    if v == "invalid_due_to_truncation":
        plain = "Comparison is invalid because one or both answers hit the token limit or trail off. Raise --tokens before judging quality."
    elif v == "changed_but_not_better":
        plain = "LOLM/NFET changed the wording, but the result is still generic. Different is not yet special."
    elif v == "meaningful_improvement_candidate":
        plain = f"LOLM/NFET produced a potentially meaningful improvement with about {round(float(latent) * 100)}% latent contribution. Final NFET control: {control}."
    elif v == "no_visible_difference":
        plain = "No visible difference. LOLM/NFET ran, but did not change the user-facing answer."
    else:
        plain = f"LOLM/NFET changed the answer, but this run does not prove it is better. Final NFET control: {control}."
    return {
        "verdict": v,
        "changed_text": b != l,
        "word_similarity": round(similarity, 3),
        "base_quality_flags": quality_flags(b),
        "lolm_quality_flags": quality_flags(l),
        "base_hit_token_limit": bool(base.get("hit_token_limit")),
        "lolm_hit_token_limit": bool(lolm.get("hit_token_limit")),
        "base_tok_per_sec": round(base.get("tok_per_sec", 0), 3),
        "lolm_tok_per_sec": round(lolm.get("tok_per_sec", 0), 3),
        "speed_cost_multiplier": round((base.get("tok_per_sec", 1e-9) or 1e-9) / max(lolm.get("tok_per_sec", 1e-9) or 1e-9, 1e-9), 2),
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
    parser.add_argument("--tokens", type=int, default=32)
    parser.add_argument("--temperature", type=float, default=0.05)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=237)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    print(f"Loading {args.profile} on {args.device}. This can take 10-90 seconds on first run.", flush=True)
    load_model(LoadRequest(profile=args.profile, device=args.device, use_graft=True, latent_backend="gru_debug"))
    print("Model loaded. Running strict base vs LOLM proof comparison.", flush=True)

    messages = [ChatMessage(role="user", content=args.prompt)]
    torch.manual_seed(args.seed)
    base = collect("BASE MODEL", ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=args.temperature, top_p=args.top_p, use_graft=False), quiet=args.quiet)
    torch.manual_seed(args.seed)
    lolm = collect("LOLM-NFET", ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=args.temperature, top_p=args.top_p, use_graft=True), quiet=args.quiet)
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
