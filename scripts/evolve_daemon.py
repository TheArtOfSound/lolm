# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Always-on local evolution daemon — LOLM keeps improving its own weights, unattended.

Runs gated evolution cycles forever (while the machine is awake). Each cycle trains the
NFET controller on fresh synthetic scenarios PLUS LOLM's own logged experience, and
promotes the new weights only if a held-out eval proves no regression. On promotion it
copies the new checkpoint to the LIVE path so the running workspace actually uses the
smarter controller. Durable: stop it, reboot, restart — it resumes from its state.

  # run it (Ctrl-C to stop):
  python -m scripts.evolve_daemon --interval 900 --device mps \
      --real-log local_ui/data/improvement_log.jsonl \
      --live-ckpt runs/nfet_controller/bootstrap_qwen06b.pt

  # always-on across reboots/logins: install the launchd agent (macOS):
  scripts/install_evolve_agent.sh
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
import time
from pathlib import Path

from lolm.evolve import run_cycle

_STOP = False


def _on_signal(signum, _frame):
    global _STOP
    _STOP = True
    print(f"[evolve] signal {signum} — finishing the current cycle then stopping", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="runs/evolve", help="durable state + checkpoints")
    p.add_argument("--interval", type=int, default=900, help="seconds between cycles")
    p.add_argument("--synth", type=int, default=140, help="synthetic sequences per cycle")
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--device", default="mps")
    p.add_argument("--real-log", default="", help="improvement_log.jsonl — learn from LOLM's own runs")
    p.add_argument("--live-ckpt", default="", help="copy promoted weights here so the live model uses them")
    p.add_argument("--max-cycles", type=int, default=0, help="0 = forever")
    args = p.parse_args()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    root = Path(args.root)
    real_log = Path(args.real_log) if args.real_log else None
    live = Path(args.live_ckpt) if args.live_ckpt else None
    print(f"[evolve] daemon up — every {args.interval}s, device={args.device}, "
          f"learning from {real_log or 'synthetic only'}", flush=True)

    n = 0
    while not _STOP:
        n += 1
        try:
            r = run_cycle(root, device=args.device, synth_n=args.synth,
                          epochs=args.epochs, real_log=real_log)
            tag = "PROMOTED" if r["weights_changed"] else "kept current"
            print(f"[evolve] cycle {r['cycle']}: {r['val_acc_before']}→{r['candidate_val_acc']} "
                  f"{tag} (best={r['best_val_acc']}, {r['experience_sequences']} experience seqs, "
                  f"{r['seconds']}s)", flush=True)
            # make the evolved weights LIVE so the running model actually uses them
            if live is not None and r["weights_changed"]:
                cur = root / "current.pt"
                if cur.exists():
                    live.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cur, live)
                    print(f"[evolve] promoted weights → live: {live}", flush=True)
        except Exception as exc:
            print(f"[evolve] cycle error (continuing): {exc}", flush=True)

        if args.max_cycles and n >= args.max_cycles:
            break
        # interruptible sleep
        for _ in range(args.interval):
            if _STOP:
                break
            time.sleep(1)

    print(f"[evolve] stopped after {n} cycle(s).", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
