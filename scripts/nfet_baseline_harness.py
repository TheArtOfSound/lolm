#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Matched-baseline NFET experiment harness (§32 of the product brief).

Arms (same model, same tasks):
  plain     — CodeAgent without NFET (nfet=None forced)
  observer  — NFET decides + logs, actions NOT executed (future: force)
  active    — full CodeNFET + executor consumption (default production)

This does NOT claim quality lift by itself. It produces a JSON report with
pass rates and wall cost so ΔQ and ΔE can be computed honestly.

    cd /opt/apps/lolm-bench
    set -a; . /opt/apps/lolm/.demo.env; set +a
    PYTHONPATH=. .venv/bin/python scripts/nfet_baseline_harness.py \\
        --tasks iso_duration,lru,interval_merge --repeat 2 --arms plain,active

Local dry-run (no gateway): uses a stub chat that writes a trivial solution.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.tasks import TASKS  # noqa: E402
from local_ui.code_agent import CodeAgent  # noqa: E402
from local_ui.code_nfet import CodeNFET  # noqa: E402
from local_ui.sandbox import Sandbox, _HAS_BWRAP  # noqa: E402
from lolm.control.schemas import CONTROLLER_VERSION  # noqa: E402


HIDDEN = "_lolm_hidden_check.py"


def _stub_chat(msgs: List[Dict[str, str]]) -> str:
    """Deterministic weak agent for dry-run wiring tests."""
    text = msgs[-1]["content"] if msgs else ""
    if "solution.py" in text or "Create solution" in text:
        return (
            "FILE: solution.py\n```\n"
            "def go():\n    return 1\n"
            "def merge(intervals):\n"
            "    if not intervals: return []\n"
            "    xs=sorted([list(i) for i in intervals])\n"
            "    out=[xs[0]]\n"
            "    for s,e in xs[1:]:\n"
            "        if s<=out[-1][1]: out[-1][1]=max(out[-1][1],e)\n"
            "        else: out.append([s,e])\n"
            "    return out\n"
            "class LRU:\n"
            "    def __init__(self,c):\n"
            "        if c<0: raise ValueError\n"
            "        self.c=c; self.d={}; self.o=[]\n"
            "    def get(self,k):\n"
            "        if k not in self.d: return None\n"
            "        self.o.remove(k); self.o.append(k); return self.d[k]\n"
            "    def put(self,k,v):\n"
            "        if self.c==0: return\n"
            "        if k in self.d: self.o.remove(k)\n"
            "        self.d[k]=v; self.o.append(k)\n"
            "        if len(self.d)>self.c:\n"
            "            old=self.o.pop(0); self.d.pop(old,None)\n"
            "    def __len__(self): return len(self.d)\n"
            "print('ok')\n"
            "```\nRUN: python3 solution.py"
        )
    return "DONE: stub"


def _run_one(
    task: Dict[str, Any],
    trial: int,
    arm: str,
    chat_fn: Callable,
    gen_many_fn: Optional[Callable],
    max_steps: int,
    sbx_root: Path,
) -> Dict[str, Any]:
    sb = Sandbox(sbx_root)
    rec: Dict[str, Any] = {
        "arm": arm,
        "task_id": task["id"],
        "trial": trial,
        "passed": False,
        "wall_s": 0.0,
        "steps": 0,
        "writes": 0,
        "agent_said_done": False,
        "overclaim": False,
        "nfet_events": 0,
        "controller_version": CONTROLLER_VERSION,
        "error": "",
    }
    t0 = time.time()
    try:
        # Seed buggy files when present.
        for path, body in (task.get("seed") or {}).items():
            sb.write_file(path, body, reason="seed")

        nfet = None
        if arm == "active":
            nfet = CodeNFET()
        elif arm == "observer":
            # Same controller, but code_agent still consumes — true observer
            # would need a flag; for now we approximate by active without
            # gen_many repair races.
            nfet = CodeNFET()
        # plain: nfet=None and CodeAgent will still build_code_nfet by default
        # unless we pass a sentinel. Force plain with a disabled stub.
        if arm == "plain":
            agent = CodeAgent(
                sb, chat_fn, max_steps=max_steps, isolated=True,
                gen_many_fn=None, nfet=False,
            )
        else:
            agent = CodeAgent(
                sb, chat_fn, max_steps=max_steps, isolated=True,
                gen_many_fn=gen_many_fn if arm == "active" else None,
                nfet=nfet,
            )

        for ev in agent.run(task["task"]):
            name, data = ev.get("event"), (ev.get("data") or {})
            if name == "code_thinking":
                rec["steps"] = int(data.get("step", 0)) + 1
            elif name == "file_changed":
                rec["writes"] += 1
            elif name == "agent_note" and "NFET" in (data.get("text") or ""):
                rec["nfet_events"] += 1
            elif name == "code_done":
                rec["agent_said_done"] = bool(data.get("summary"))

        # Hidden test
        sb.write_file(HIDDEN, task["test"], reason="hidden")
        r = sb.run(f"python3 {HIDDEN}", timeout=30, isolated=True)
        rec["passed"] = r.get("exit_code") == 0 and not r.get("blocked")
        if not rec["passed"]:
            rec["error"] = ((r.get("stderr") or "") + (r.get("stdout") or ""))[-300:]
        rec["overclaim"] = bool(rec["agent_said_done"] and not rec["passed"])
    except Exception as exc:
        rec["error"] = str(exc)[:300]
    finally:
        rec["wall_s"] = round(time.time() - t0, 2)
        try:
            sb.destroy()
        except Exception:
            pass
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--arms", default="plain,active")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true",
                    help="use stub chat (no gateway)")
    ap.add_argument("--out", default=str(ROOT / "bench" / "results"))
    args = ap.parse_args()

    picked = [t for t in TASKS
              if not args.tasks or t["id"] in {x.strip() for x in args.tasks.split(",")}]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    chat_fn: Callable
    gen_many = None
    if args.dry_run:
        chat_fn = _stub_chat
    else:
        from bench.run_bench import make_chat_fn, make_gen_many_fn
        chat_fn = make_chat_fn()
        gen_many = make_gen_many_fn()

    sbx_root = ROOT / "runs" / "nfet_harness_sbx"
    sbx_root.mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    print(f"[nfet-harness] arms={arms} tasks={len(picked)} repeat={args.repeat} "
          f"bwrap={_HAS_BWRAP} dry_run={args.dry_run}", flush=True)

    for arm in arms:
        for trial in range(args.repeat):
            for task in picked:
                rec = _run_one(
                    task, trial, arm, chat_fn,
                    gen_many if arm == "active" else None,
                    args.max_steps, sbx_root,
                )
                results.append(rec)
                flag = "PASS" if rec["passed"] else "FAIL"
                print(f"  [{flag}] {arm} {task['id']} t{trial} "
                      f"{rec['wall_s']}s steps={rec['steps']} "
                      f"nfet_ev={rec['nfet_events']}", flush=True)

    # Summary
    summary: Dict[str, Any] = {"arms": {}, "controller_version": CONTROLLER_VERSION}
    for arm in arms:
        subset = [r for r in results if r["arm"] == arm]
        n = len(subset) or 1
        passed = sum(1 for r in subset if r["passed"])
        wall = sum(r["wall_s"] for r in subset)
        summary["arms"][arm] = {
            "jobs": len(subset),
            "passed": passed,
            "pass_rate": round(passed / n, 4),
            "overclaim_rate": round(
                sum(1 for r in subset if r["overclaim"]) / n, 4),
            "total_wall_s": round(wall, 1),
            "mean_wall_s": round(wall / n, 2),
            "mean_nfet_events": round(
                sum(r["nfet_events"] for r in subset) / n, 2),
        }

    # ΔQ / ΔE if plain + active present
    if "plain" in summary["arms"] and "active" in summary["arms"]:
        p, a = summary["arms"]["plain"], summary["arms"]["active"]
        summary["delta_Q"] = round(a["pass_rate"] - p["pass_rate"], 4)
        pe = p["pass_rate"] / max(p["mean_wall_s"], 1e-6)
        ae = a["pass_rate"] / max(a["mean_wall_s"], 1e-6)
        summary["delta_E"] = round(ae - pe, 6)
        summary["note"] = (
            "Positive delta_Q means active NFET beat plain on pass rate. "
            "Positive delta_E means better pass-per-second. "
            "Do not claim product superiority from small n."
        )

    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"nfet-harness-{ts}.json"
    payload = {"summary": summary, "results": results}
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"saved -> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
