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


def _consumed(root: Path) -> set:
    try:
        return set(json.loads((root / "consumed.json").read_text()))
    except Exception:
        return set()


def _mark_consumed(root: Path, qs) -> None:
    done = _consumed(root)
    done.update(qs)
    (root / "consumed.json").write_text(json.dumps(sorted(done)[-2000:]))


def _pull_remote(url: str, queue: Path, root: Path) -> int:
    """The thought→weight bridge: pull facts LOLM minted while thinking on the box
    (life pulses / nightly reflection) and merge them into the local training queue.
    A 3am thought on the server becomes trained weights the next cycle here.
    Consumed facts never re-train."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            facts = json.loads(r.read().decode()).get("facts", [])
    except Exception as e:
        print(f"[knowledge] pull failed (continuing local-only): {str(e)[:100]}", flush=True)
        return 0
    have = {d.get("q") for d in _read_queue(queue)} | _consumed(root)
    fresh = [f for f in facts if f.get("q") and f.get("a") and f["q"] not in have]
    if fresh:
        with queue.open("a", encoding="utf-8") as fh:
            for f in fresh:
                fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    return len(fresh)


def _restart_served_weights() -> None:
    """serve_evolved.py loads the adapter once at start; after a promotion, kill it and
    let launchd's KeepAlive bring it back serving the NEW weights immediately."""
    subprocess.run(["pkill", "-f", "serve_evolved"], capture_output=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="runs/evolve_knowledge")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--interval", type=int, default=1800)
    p.add_argument("--batch", type=int, default=4, help="facts learned per cycle")
    p.add_argument("--pull-url", default="",
                   help="pull facts LOLM minted while thinking (e.g. "
                        "https://lolm.imagineqira.com/api/demo/life/facts)")
    p.add_argument("--max-cycles", type=int, default=0)
    args = p.parse_args()
    signal.signal(signal.SIGTERM, _sig); signal.signal(signal.SIGINT, _sig)

    root = Path(args.root); root.mkdir(parents=True, exist_ok=True)
    queue = root / "queue.jsonl"
    print(f"[knowledge] daemon up — every {args.interval}s, batch={args.batch}, "
          f"queue={queue}" + (f", pulling {args.pull_url}" if args.pull_url else ""), flush=True)

    n = 0
    while not _STOP:
        n += 1
        if args.pull_url:
            pulled = _pull_remote(args.pull_url, queue, root)
            if pulled:
                print(f"[knowledge] pulled {pulled} fact(s) LOLM thought up on the box", flush=True)
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
                    _mark_consumed(root, [d["q"] for d in batch])  # never re-train them
                    _restart_served_weights()                      # fresh weights serve NOW
                    print("[knowledge] promoted → served weights restarted with the new adapter",
                          flush=True)
                else:
                    # CRITICAL: do not forever retrain the same unlearnable head-of-queue
                    # fact (that produced learned=0.0 for dozens of cycles). Rotate and
                    # drop after repeated failures.
                    att_path = root / "fact_attempts.json"
                    try:
                        att = json.loads(att_path.read_text())
                    except Exception:
                        att = {}
                    for d in batch:
                        q = d.get("q") or ""
                        att[q] = int(att.get(q, 0)) + 1
                    # rotate failed batch to the back; drop if attempts >= 3
                    rest = pending[args.batch:]
                    recycle, drop = [], []
                    for d in batch:
                        q = d.get("q") or ""
                        if int(att.get(q, 0)) >= 3:
                            drop.append(q)
                        else:
                            recycle.append(d)
                    _write_queue(queue, rest + recycle)
                    if drop:
                        _mark_consumed(root, drop)
                        for q in drop:
                            att.pop(q, None)
                        print(f"[knowledge] dropped {len(drop)} unlearnable fact(s)", flush=True)
                    att_path.write_text(json.dumps(att, indent=2))
            except Exception as e:
                print(f"[knowledge] cycle error (continuing): {str(e)[:160]}", flush=True)

        if args.max_cycles and n >= args.max_cycles:
            break
        for _ in range(args.interval):
            if _STOP:
                break
            time.sleep(1)
    print(f"[knowledge] stopped after {n} cycle(s).", flush=True)


if __name__ == "__main__":
    main()
