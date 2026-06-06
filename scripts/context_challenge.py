#!/usr/bin/env python3
"""Local context challenge for LOLM-NFET.

This script writes a clear project fact into local memory, then compares base
mode and LOLM-NFET mode on whether they use that fact in the answer. It is a
product-layer test: memory/context must create visible consequence.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

import torch

import local_ui.server as server
from local_ui.server import ChatMessage, ChatRequest, LoadRequest, generation_loop, load_model

FACT = "Project rule: LOLM-NFET is special only when it creates visible consequence, not when it merely displays telemetry."
GOAL = "Prove LOLM-NFET creates visible consequence through memory, verification, retrieval, or correction."


def seed_context() -> None:
    server.MEMORY.append_note(FACT, tag="context_challenge", importance=10)
    server.MEMORY.append_identity_line(FACT)
    goals = server.MEMORY.get_goals()
    if not any(g.get("title") == GOAL for g in goals):
        server.MEMORY.add_goal(GOAL, why="A special local AI must show consequence, not just internal gauges.", priority=10)


def collect(label: str, req: ChatRequest, quiet: bool = False) -> Dict[str, Any]:
    start = time.perf_counter()
    final = None
    text = ""
    tokens = 0
    print(f"\n=== {label} ===", flush=True)
    for event in generation_loop(req):
        kind = event.get("event")
        data = event.get("data", {})
        if kind == "token":
            tok = data.get("token", "")
            text += tok
            tokens += 1
            if not quiet:
                print(tok, end="", flush=True)
        elif kind == "done":
            final = data
        elif kind == "error":
            raise RuntimeError(data.get("error", "generation failed"))
    elapsed = max(time.perf_counter() - start, 1e-9)
    if final is None:
        final = {"response": text, "tokens": tokens}
    final["seconds"] = elapsed
    final["tok_per_sec"] = tokens / elapsed
    final["hit_token_limit"] = int(final.get("tokens", tokens) or tokens) >= int(req.max_new_tokens)
    print(f"\n[{label}] tokens={tokens} seconds={elapsed:.2f} tok/s={tokens / elapsed:.3f}", flush=True)
    return final


def flags(text: str) -> Dict[str, bool]:
    lower = (text or "").lower()
    return {
        "visible_consequence": "visible consequence" in lower,
        "not_telemetry": "not telemetry" in lower or "merely displays telemetry" in lower,
        "memory": "memory" in lower,
        "verification": "verification" in lower or "verify" in lower,
        "retrieval": "retrieval" in lower or "retrieve" in lower,
        "correction": "correction" in lower or "correct" in lower,
    }


def score(text: str) -> int:
    return sum(flags(text).values())


def make_verdict(base: Dict[str, Any], lolm: Dict[str, Any]) -> Dict[str, Any]:
    base_text = base.get("response", "") or ""
    lolm_text = lolm.get("response", "") or ""
    base_score = score(base_text)
    lolm_score = score(lolm_text)
    summary = lolm.get("summary", {}) or {}
    if base.get("hit_token_limit") or lolm.get("hit_token_limit"):
        verdict = "invalid_due_to_truncation"
        plain = "Raise --tokens. One or both answers hit the token limit."
    elif lolm_score >= 3 and lolm_score > base_score:
        verdict = "context_challenge_passed"
        plain = "LOLM-NFET used local project context in a visible way and beat the base run."
    elif lolm_score > base_score:
        verdict = "context_signal_detected"
        plain = "LOLM-NFET used more local context than base, but the win is still weak."
    elif base_score >= 3 and lolm_score >= 3:
        verdict = "context_used_by_both"
        plain = "Both paths used local context. This proves AutoContext works, but not graft superiority."
    else:
        verdict = "context_challenge_failed"
        plain = "Neither path made the local context feel useful enough."
    return {
        "verdict": verdict,
        "plain": plain,
        "base_score": base_score,
        "lolm_score": lolm_score,
        "base_flags": flags(base_text),
        "lolm_flags": flags(lolm_text),
        "base_tok_per_sec": round(base.get("tok_per_sec", 0), 3),
        "lolm_tok_per_sec": round(lolm.get("tok_per_sec", 0), 3),
        "avg_latent_share": summary.get("avg_latent_share"),
        "last_control": summary.get("last_control"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="qwen3_0_6b_smoke")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--tokens", type=int, default=80)
    parser.add_argument("--temperature", type=float, default=0.05)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=237)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    seed_context()
    print("Seeded local memory and goal for context challenge.", flush=True)
    load_model(LoadRequest(profile=args.profile, device=args.device, use_graft=True, latent_backend="gru_debug"))
    prompt = "What is the exact project rule for what makes LOLM-NFET special? Answer in one complete paragraph."
    messages = [ChatMessage(role="user", content=prompt)]

    torch.manual_seed(args.seed)
    base = collect("BASE MODE / AUTOCONTEXT / NO GRAFT", ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=args.temperature, top_p=args.top_p, use_graft=False), quiet=args.quiet)
    torch.manual_seed(args.seed)
    lolm = collect("LOLM-NFET / AUTOCONTEXT / GRAFT", ChatRequest(messages=messages, max_new_tokens=args.tokens, temperature=args.temperature, top_p=args.top_p, use_graft=True), quiet=args.quiet)
    verdict = make_verdict(base, lolm)
    server.append_improvement_event({"type": "context_challenge", "timestamp": time.time(), "verdict": verdict, "base_id": base.get("id"), "lolm_id": lolm.get("id")})

    print("\n=== BASE FINAL ===\n")
    print(base.get("response", ""))
    print("\n=== LOLM-NFET FINAL ===\n")
    print(lolm.get("response", ""))
    print("\n=== CONTEXT CHALLENGE VERDICT ===\n")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
