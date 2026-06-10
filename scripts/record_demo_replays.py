"""Record real NFET agent runs as the public demo replay library.

Runs the actual model with the bootstrapped controller and demo-sized budgets
(so replays look exactly like live runs on the public box), captures the full
event stream of each run, and writes site/replays/<id>.json plus index.json.

Usage:
    PYTHONPATH=. python scripts/record_demo_replays.py \
        --ckpt runs/nfet_controller/bootstrap_qwen06b.pt --device mps
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from local_ui import server as workspace
from local_ui.nfet_agent import AgentDeps, NFETAgent, NFETAgentRequest

COMMANDS = [
    ("gate", "Explain the manifestation gate in LOLM and why it matters"),
    ("dependency-inversion", "What is dependency inversion in the LOLM architecture?"),
    ("eval-plan", "Write a short plan to evaluate a 304M language model against Pythia-410M"),
    ("entropy-retrieve", "Why should an agent retrieve evidence when its token entropy spikes?"),
    ("five-controls", "Summarize what the NFET controller's five actions do"),
]

SEED_NOTES = [
    ("LOLM fuses five streams: surface decoder h, latent SSM z, regime layer r, persistent memory m, and a manifestation gate g that arbitrates surface vs latent per dimension.", "research", 5),
    ("Dependency inversion: the latent SSM path is only ~29 percent of the fused representation, but forcing the gate to surface-only explodes perplexity from 34.47 to 485 million.", "research", 5),
    ("LOLM-304M beats Pythia-410M on WikiText-103: eval PPL 68.4 vs 142.9 with 26 percent fewer parameters; late-position BPC 1.02 vs 1.23.", "research", 5),
    ("The NFET controller maps telemetry (logit entropy, hidden drift, gate mean, regime entropy) to five controls: continue, retrieve, verify, branch, finalize.", "research", 5),
    ("High sustained token entropy means the model is uncertain about continuations; retrieving evidence reduces uncertainty better than continuing to guess.", "research", 4),
    ("Evaluation practice: match training data and tokenizer, report perplexity windows, late-position bits-per-character, and distinct-n generation diversity.", "research", 4),
]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="qwen3_0_6b_smoke")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ckpt", default="runs/nfet_controller/bootstrap_qwen06b.pt")
    parser.add_argument("--out", default="site/replays")
    parser.add_argument("--segments", type=int, default=3)
    parser.add_argument("--segment-tokens", type=int, default=28)
    parser.add_argument("--final-tokens", type=int, default=96)
    parser.add_argument("--only", default="", help="comma-separated replay ids to re-record")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for text, tag, importance in SEED_NOTES:
        existing = workspace.MEMORY.search_notes(text[:40], limit=1)
        if not existing:
            workspace.MEMORY.append_note(text, tag=tag, importance=importance)

    print(f"loading {args.profile} on {args.device} (ckpt={args.ckpt})...", flush=True)
    t0 = time.time()
    try:
        info = workspace.load_model(workspace.LoadRequest(
            profile=args.profile, device=args.device,
            graft_checkpoint=args.ckpt or None,
        ))
    except Exception as exc:
        if args.device != "cpu":
            print(f"{args.device} load failed ({exc}); retrying on cpu", flush=True)
            args.device = "cpu"
            info = workspace.load_model(workspace.LoadRequest(
                profile=args.profile, device="cpu",
                graft_checkpoint=args.ckpt or None,
            ))
        else:
            raise
    print(f"loaded in {time.time() - t0:.1f}s head_trained={info.get('head_trained')}", flush=True)

    agent = NFETAgent(AgentDeps(
        memory=workspace.MEMORY,
        ChatMessage=workspace.ChatMessage,
        ChatRequest=workspace.ChatRequest,
        generation_loop=workspace.generation_loop,
        append_event=workspace.append_improvement_event,
        head_trained_fn=lambda: workspace.STATE.head_trained,
    ))

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    index = {"replays": []}
    existing_index = out_dir / "index.json"
    if existing_index.exists():
        try:
            index = json.loads(existing_index.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    for rid, command in COMMANDS:
        if only and rid not in only:
            continue
        print(f"\n=== recording '{rid}': {command}", flush=True)
        started = time.time()
        req = NFETAgentRequest(
            command=command,
            max_segments=args.segments,
            segment_tokens=args.segment_tokens,
            final_tokens=args.final_tokens,
            max_retrieves=1, max_verifies=1, max_branches=1,
        )
        events = []
        for event in agent.run_events(req):
            events.append(event)
            if event["event"] == "decision":
                d = event["data"]["decision"]
                print(f"  seg {event['data']['segment']}: {d['label']} [{d['source']}]", flush=True)
        seconds = round(time.time() - started, 1)
        done = next((e["data"] for e in events if e["event"] == "run_done"), {})
        proof = done.get("proof", {})
        meta = {
            "id": rid,
            "title": command,
            "command": command,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seconds": seconds,
            "head_trained": done.get("head_trained"),
            "ended_by": done.get("ended_by"),
            "verdict": proof.get("verdict"),
            "control_counts": proof.get("control_counts"),
            "counters": done.get("counters"),
        }
        (out_dir / f"{rid}.json").write_text(
            json.dumps({"meta": meta, "events": events}, ensure_ascii=False),
            encoding="utf-8",
        )
        index["replays"] = [r for r in index.get("replays", []) if r.get("id") != rid]
        index["replays"].append(meta)
        existing_index.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  saved {rid}.json ({seconds}s, verdict={meta['verdict']})", flush=True)

    print(f"\ndone: {len(index['replays'])} replays in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
