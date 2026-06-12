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
from scripts.seed_workspace_notes import seed as seed_notes

COMMANDS = [
    ("hello", "Hello!"),
    ("used-car", "What should I look for when buying a used car?"),
    ("credit-score", "How does a credit score actually work?"),
    ("start-running", "Give me a simple 3-step plan to start running"),
    ("trustworthy-ai", "What makes an AI agent trustworthy?"),
    ("sky-blue", "Why is the sky blue?"),
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
    parser.add_argument("--id-suffix", default="", help="suffix for replay ids (e.g. -4b)")
    parser.add_argument("--model-label", default="", help="model badge shown in pickers (e.g. 4B)")
    parser.add_argument("--reasoner", default="local", help="local | workers_ai (frontier writes, graft telemeters)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_notes(workspace.MEMORY)

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

    frontier = None
    if args.reasoner != "local":
        from local_ui.workers_ai_reasoner import WorkersAIReasonerLoop
        frontier = WorkersAIReasonerLoop(state_fn=lambda: workspace.STATE)
        print(f"frontier reasoner: {args.reasoner} (available={frontier.available()})", flush=True)

    agent = NFETAgent(AgentDeps(
        memory=workspace.MEMORY,
        ChatMessage=workspace.ChatMessage,
        ChatRequest=workspace.ChatRequest,
        generation_loop=workspace.generation_loop,
        append_event=workspace.append_improvement_event,
        head_trained_fn=lambda: workspace.STATE.head_trained,
        frontier_loop=frontier,
    ))

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    index = {"replays": []}
    existing_index = out_dir / "index.json"
    if existing_index.exists():
        try:
            index = json.loads(existing_index.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    for base_rid, command in COMMANDS:
        if only and base_rid not in only:
            continue
        rid = base_rid + args.id_suffix
        print(f"\n=== recording '{rid}': {command}", flush=True)
        started = time.time()
        req = NFETAgentRequest(
            command=command,
            reasoner=args.reasoner,
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
            "model": args.model_label or None,
            "profile": args.profile,
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
