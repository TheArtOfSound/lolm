# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Always-on KNOWLEDGE daemon — the local model keeps learning new facts, gated,
unattended, and serves the evolved weights back so it uses what it learns.

Reads a fact queue (runs/evolve_knowledge/queue.jsonl, one {"q","a","target"} per line —
append to it from anywhere: your conversations, a scraper, HF ingest). Each cycle takes a
batch, LoRA-fine-tunes the local model on it + a rehearsal anchor set, and PROMOTES only if
a held-out eval proves it learned the facts without forgetting the anchors. Promoted facts
are removed from the queue; the cumulative adapter at runs/evolve_knowledge/live becomes the
new weights. With --serve, it (re)launches `mlx_lm.server` on the promoted adapter so the
sovereign brain (LOLM_LOCAL_API=openai, LOLM_LOCAL_URL=http://127.0.0.1:<port>) uses it live.

  python scripts/evolve_knowledge_daemon.py --interval 1800 --serve
  # seed the queue:
  echo '{"q":"Who founded Qira?","a":"Qira was founded by Bryan.","target":"bryan"}' >> runs/evolve_knowledge/queue.jsonl
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from lolm.evolve_knowledge import DEFAULT_MODEL, run_knowledge_cycle

# general-knowledge anchors rehearsed every cycle to prevent catastrophic forgetting
ANCHORS = [
    ("What is the capital of France?", "The capital of France is Paris."),
    ("What is 2 + 2?", "2 + 2 = 4."),
    ("What is the capital of Japan?", "The capital of Japan is Tokyo."),
    ("What color is the sky on a clear day?", "The sky is blue on a clear day."),
    ("Who wrote Romeo and Juliet?", "William Shakespeare wrote Romeo and Juliet."),
    ("What is the largest planet?", "Jupiter is the largest planet."),
]
ANCHOR_CONTROLS = [("What is the capital of France?", "paris"), ("What is 2 + 2?", "4"),
                   ("What is the capital of Japan?", "tokyo")]
_STOP = False


def _sig(s, f):
    global _STOP
    _STOP = True
    print(f"[knowledge] signal {s} — stopping after this cycle", flush=True)


def _read_queue(p: Path):
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        try:
            d = json.loads(ln)
            if d.get("q") and d.get("a"):
                out.append(d)
        except Exception:
            pass
    return out


def _write_queue(p: Path, items):
    p.write_text("\n".join(json.dumps(i) for i in items) + ("\n" if items else ""))


def _serve(model, adapter: Path, port: int):
    if not adapter.exists():
        return None
    return subprocess.Popen([sys.executable, "-m", "mlx_lm", "server", "--model", model,
                             "--adapter-path", str(adapter), "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="runs/evolve_knowledge")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--interval", type=int, default=1800)
    p.add_argument("--batch", type=int, default=4, help="facts learned per cycle")
    p.add_argument("--serve", action="store_true", help="(re)serve the promoted adapter")
    p.add_argument("--port", type=int, default=11435)
    p.add_argument("--max-cycles", type=int, default=0)
    args = p.parse_args()
    signal.signal(signal.SIGTERM, _sig); signal.signal(signal.SIGINT, _sig)

    root = Path(args.root); root.mkdir(parents=True, exist_ok=True)
    queue = root / "queue.jsonl"
    server = None
    print(f"[knowledge] daemon up — every {args.interval}s, batch={args.batch}, "
          f"queue={queue}", flush=True)

    n = 0
    while not _STOP:
        n += 1
        pending = _read_queue(queue)
        if not pending:
            print("[knowledge] queue empty — waiting", flush=True)
        else:
            batch = pending[:args.batch]
            new_facts = [(d["q"], d["a"]) for d in batch]
            probes = [(d["q"], (d.get("target") or d["a"]).lower()) for d in batch]
            try:
                r = run_knowledge_cycle(root, model=args.model, new_facts=new_facts,
                                        rehearsal=ANCHORS, probes=probes,
                                        control_probes=ANCHOR_CONTROLS)
                tag = "PROMOTED" if r["weights_changed"] else "kept current"
                print(f"[knowledge] cycle {r['cycle']}: learned={r['new_facts_known_after']} "
                      f"keep={r['control_retention']} {tag} ({r['seconds']}s)", flush=True)
                if r["weights_changed"]:
                    _write_queue(queue, pending[args.batch:])      # drop learned facts
                    if args.serve:
                        if server:
                            server.terminate()
                        server = _serve(args.model, root / "live", args.port)
                        print(f"[knowledge] serving evolved weights on :{args.port}", flush=True)
            except Exception as e:
                print(f"[knowledge] cycle error (continuing): {str(e)[:160]}", flush=True)

        if args.max_cycles and n >= args.max_cycles:
            break
        for _ in range(args.interval):
            if _STOP:
                break
            time.sleep(1)
    if server:
        server.terminate()
    print(f"[knowledge] stopped after {n} cycle(s).", flush=True)


if __name__ == "__main__":
    main()
