"""End-to-end smoke for the NFET agent on a real local model.

Loads the backbone + graft (optionally with a trained controller checkpoint),
seeds a little memory, runs one NFET agent command, and prints the control
timeline plus the proof receipt.

    PYTHONPATH=. python scripts/smoke_nfet_agent.py \
        --ckpt runs/nfet_controller/bootstrap_qwen06b.pt \
        --command "Explain what the manifestation gate does in LOLM."
"""

from __future__ import annotations

import argparse
import json
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="qwen3_0_6b_smoke")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ckpt", default="", help="trained controller checkpoint (arms the head)")
    parser.add_argument("--command", default="Explain what the manifestation gate does in LOLM and why it matters.")
    parser.add_argument("--reasoner", default="local", choices=["local", "claude"])
    parser.add_argument("--max-segments", type=int, default=3)
    parser.add_argument("--segment-tokens", type=int, default=32)
    parser.add_argument("--final-tokens", type=int, default=96)
    args = parser.parse_args()

    from local_ui import server as workspace
    from local_ui.claude_reasoner import ClaudeReasonerLoop
    from local_ui.internet_tools import web_search
    from local_ui.nfet_agent import AgentDeps, NFETAgent, NFETAgentRequest

    print(f"loading {args.profile} on {args.device} (ckpt={args.ckpt or 'none'})...")
    t0 = time.time()
    info = workspace.load_model(workspace.LoadRequest(
        profile=args.profile, device=args.device,
        graft_checkpoint=args.ckpt or None,
    ))
    print(f"loaded in {time.time() - t0:.1f}s: hidden={info['hidden_size']} head_trained={info['head_trained']}")

    memory = workspace.MEMORY
    if not memory.search_notes("manifestation gate", limit=1):
        memory.append_note(
            "The manifestation gate is a per-dimension sigmoid that arbitrates between "
            "the surface decoder and the latent SSM; trained models settle near g=0.72.",
            tag="research", importance=5,
        )
        memory.append_note(
            "Gate ablation at 1.57B: forcing g=1.0 (surface only) explodes perplexity to "
            "485 million — dependency inversion.", tag="research", importance=5,
        )

    agent = NFETAgent(AgentDeps(
        memory=memory,
        ChatMessage=workspace.ChatMessage,
        ChatRequest=workspace.ChatRequest,
        generation_loop=workspace.generation_loop,
        append_event=workspace.append_improvement_event,
        head_trained_fn=lambda: workspace.STATE.head_trained,
        web_search=web_search,
        frontier_loop=ClaudeReasonerLoop(lambda: workspace.STATE),
    ))

    t0 = time.time()
    out = agent.run(NFETAgentRequest(
        command=args.command, reasoner=args.reasoner,
        max_segments=args.max_segments, segment_tokens=args.segment_tokens,
        final_tokens=args.final_tokens,
    ))
    elapsed = time.time() - t0

    print(f"\n=== CONTROL TIMELINE ({elapsed:.1f}s, ended_by={out['ended_by']}) ===")
    for entry in out["timeline"]:
        decision = entry["decision"]
        print(f"  seg {entry['segment']}: {decision['label']:9s} [{decision['source']}] "
              f"z={decision['zscores']} -> {entry['action']['kind']}")
        print(f"      {decision['reason']}")
    print("\n=== PROOF ===")
    print(json.dumps(out["proof"], indent=2))
    print("\n=== ANSWER ===")
    print(out["result"]["response"][:1500])


if __name__ == "__main__":
    main()
