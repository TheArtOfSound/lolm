#!/usr/bin/env python3
"""Score the LOLM code agent objectively.

For each task: fresh jailed sandbox -> (optional buggy seed files) -> run the real
CodeAgent loop with the real driver model -> THEN drop in a hidden test the agent
never saw and run it. Exit 0 on the hidden test is the only thing that counts as a
pass, so "the agent said DONE" and "the agent's own asserts went green" cannot
inflate the score.

Run on the Linux box (bwrap required for a jailed run):
    cd /opt/apps/lolm-bench
    set -a; . /opt/apps/lolm/.demo.env; set +a
    PYTHONPATH=. .venv/bin/python bench/run_bench.py --label baseline

    --tasks a,b,c   only these task ids
    --repeat N      run every task N times (the loop is stochastic; N>1 gives a
                    pass RATE instead of a coin flip)
    --workers N     task-level parallelism (the gateway is the bottleneck, not CPU)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.tasks import TASKS                                    # noqa: E402
from local_ui.code_agent import CodeAgent                        # noqa: E402
from local_ui.sandbox import Sandbox, _HAS_BWRAP                 # noqa: E402

# A name the agent has no reason to create, written only after the loop is done.
HIDDEN = "_lolm_hidden_check.py"

# Mirrors local_ui/server_public_demo.py::_operator_chat + code_routes' 2400-token
# wrap, and workers_ai_reasoner._generate's want*3 expansion. Same driver, same
# knobs as a real /api/demo/code/run — otherwise the score measures the wrong thing.
GEN_MAX_NEW_TOKENS = 2400
GEN_MULT = 3
GEN_CAP = 8192


class GatewayError(RuntimeError):
    pass


def make_chat_fn(model: str = "") -> Any:
    url = os.environ.get("WORKERS_AI_URL", "")
    secret = os.environ.get("WORKERS_AI_SECRET", "")
    if not (url and secret):
        raise SystemExit("WORKERS_AI_URL / WORKERS_AI_SECRET not set — "
                         "source /opt/apps/lolm/.demo.env first")
    model = model or os.environ.get("WORKERS_AI_MODEL",
                                    "@cf/meta/llama-3.3-70b-instruct-fp8-fast")

    def chat(messages: List[Dict[str, str]], max_new_tokens: int = GEN_MAX_NEW_TOKENS) -> str:
        n_tokens = min(max(int(max_new_tokens) * GEN_MULT, 96), GEN_CAP)
        payload = {"messages": [{"role": m.get("role", "user"),
                                 "content": str(m.get("content") or "")}
                                for m in messages],
                   "max_tokens": n_tokens,
                   "model": model}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {secret}",
                     "User-Agent": "lolm-nfet-origin/1.0"})
        last = ""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=min(30 + n_tokens / 40.0, 150)) as r:
                    body = json.loads(r.read())
                break
            except Exception as exc:                     # transient gateway/cascade blip
                last = f"{type(exc).__name__}: {exc}"
                if attempt == 2:
                    raise GatewayError(last) from exc
                time.sleep(1.5 * (attempt + 1))
        # The worker fronts a provider cascade, so accept every shape it may return.
        if isinstance(body, dict):
            for key in ("response", "result", "text", "content"):
                v = body.get(key)
                if isinstance(v, str) and v.strip():
                    return v
                if isinstance(v, dict):
                    for k2 in ("response", "text", "content"):
                        if isinstance(v.get(k2), str) and v[k2].strip():
                            return v[k2]
            ch = body.get("choices")
            if isinstance(ch, list) and ch:
                msg = (ch[0] or {}).get("message") or {}
                if isinstance(msg.get("content"), str):
                    return msg["content"]
                if isinstance((ch[0] or {}).get("text"), str):
                    return ch[0]["text"]
        raise GatewayError(f"unrecognized gateway response: {str(body)[:300]}")

    return chat


def run_one(task: Dict[str, Any], chat_fn: Any, root: Path, *,
            max_steps: int, run_timeout: int, trial: int) -> Dict[str, Any]:
    t0 = time.time()
    rec: Dict[str, Any] = {"id": task["id"], "tier": task.get("tier", "impl"),
                           "trial": trial, "passed": False, "steps": 0,
                           "wall_s": 0.0, "agent_said_done": False,
                           "receipt_ok": None, "files": [], "writes": 0,
                           "runs": 0, "green_runs": 0, "hidden_stderr": "",
                           "error": "", "stuck": False, "budget_hit": False}
    sb = Sandbox(str(root))
    try:
        for path, content in (task.get("seed") or {}).items():
            sb.write_file(path, content, reason="bench seed")
        seeded = sorted((task.get("seed") or {}).keys())

        agent = CodeAgent(sb, chat_fn, max_steps=max_steps,
                          run_timeout=run_timeout, isolated=True)
        for ev in agent.run(task["task"]):
            name, data = ev.get("event"), (ev.get("data") or {})
            if name == "code_thinking":
                rec["steps"] = int(data.get("step", 0)) + 1
            elif name == "file_changed":
                rec["writes"] += 1
            elif name == "command_finished":
                rec["runs"] += 1
                if data.get("exit_code") == 0 and not data.get("blocked"):
                    rec["green_runs"] += 1
            elif name == "code_done":
                rec["agent_said_done"] = bool(data.get("summary"))
                rec["receipt_ok"] = data.get("ok")
                rec["stuck"] = bool(data.get("stuck"))
                rec["budget_hit"] = bool(data.get("budget_hit"))
            elif name == "error":
                rec["error"] = str(data.get("error"))[:300]

        rec["files"] = [f for f in sb.list_files(limit=60) if not f.startswith("__pycache__")]
        rec["seed_deleted"] = [p for p in seeded if p not in rec["files"]]

        # Hidden test lands only now — after the loop can no longer see or edit it.
        sb.write_file(HIDDEN, task["test"], reason="hidden grader")
        res = sb.run(f"python3 {HIDDEN}", timeout=45, isolated=True)
        rec["passed"] = (res.get("exit_code") == 0 and not res.get("blocked")
                         and "OK" in (res.get("stdout") or ""))
        if not rec["passed"]:
            tail = ((res.get("stderr") or "") + (res.get("stdout") or "")).strip()
            rec["hidden_stderr"] = tail[-700:]
            rec["hidden_exit"] = res.get("exit_code")
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
        rec["traceback"] = traceback.format_exc()[-900:]
    finally:
        rec["wall_s"] = round(time.time() - t0, 1)
        try:
            sb.destroy()
        except Exception:
            pass
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=22)
    ap.add_argument("--run-timeout", type=int, default=25)
    ap.add_argument("--model", default="")
    ap.add_argument("--out", default=str(ROOT / "bench" / "results"))
    args = ap.parse_args()

    if not _HAS_BWRAP:
        print("WARNING: bwrap missing — running UNJAILED is not comparable to prod",
              file=sys.stderr)

    picked = [t for t in TASKS
              if not args.tasks or t["id"] in {x.strip() for x in args.tasks.split(",")}]
    if not picked:
        raise SystemExit(f"no tasks matched {args.tasks!r}")

    chat_fn = make_chat_fn(args.model)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sbx_root = ROOT / "runs" / "bench_sandboxes"
    sbx_root.mkdir(parents=True, exist_ok=True)

    jobs = [(t, i) for i in range(args.repeat) for t in picked]
    print(f"[bench] label={args.label} tasks={len(picked)} repeat={args.repeat} "
          f"jobs={len(jobs)} workers={args.workers} max_steps={args.max_steps}",
          flush=True)

    started = time.time()
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(run_one, t, chat_fn, sbx_root,
                            max_steps=args.max_steps, run_timeout=args.run_timeout,
                            trial=i): (t["id"], i) for t, i in jobs}
        for fut in as_completed(futs):
            tid, trial = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:
                r = {"id": tid, "trial": trial, "passed": False,
                     "error": f"{type(exc).__name__}: {exc}"[:300], "wall_s": 0.0}
            results.append(r)
            mark = "PASS" if r.get("passed") else "FAIL"
            extra = ""
            if not r.get("passed"):
                why = (r.get("error") or r.get("hidden_stderr") or "").strip().splitlines()
                extra = f" :: {why[-1][:130]}" if why else ""
            print(f"  [{mark}] {tid} t{trial} {r.get('wall_s')}s "
                  f"steps={r.get('steps')} writes={r.get('writes')} "
                  f"green={r.get('green_runs')}/{r.get('runs')}"
                  f"{extra}", flush=True)

    total_wall = round(time.time() - started, 1)
    passed = [r for r in results if r.get("passed")]
    by_task: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        by_task.setdefault(r["id"], []).append(r)

    # The number that matters most: the sealed RECEIPT said the run was ok while the
    # hidden test says the code is wrong. Keyed on receipt_ok rather than "the model
    # emitted a summary", because the receipt is what the product actually asserts to
    # a user — and a summary that reads "INCOMPLETE — does not compile" is an honest
    # report, not an overclaim.
    overclaims = [r for r in results if r.get("receipt_ok") and not r.get("passed")]
    walls = [r.get("wall_s", 0.0) for r in results if r.get("wall_s")]

    summary = {
        "label": args.label,
        "model": args.model or os.environ.get("WORKERS_AI_MODEL", "default"),
        "jobs": len(results),
        "passed": len(passed),
        "pass_rate": round(len(passed) / max(len(results), 1), 3),
        "overclaim_rate": round(len(overclaims) / max(len(results), 1), 3),
        "median_wall_s": round(statistics.median(walls), 1) if walls else 0.0,
        "total_wall_s": total_wall,
        "max_steps": args.max_steps,
        "by_tier": {},
        "by_task": {tid: {"pass": sum(1 for x in rs if x.get("passed")), "of": len(rs)}
                    for tid, rs in sorted(by_task.items())},
    }
    for tier in sorted({r.get("tier", "impl") for r in results}):
        rs = [r for r in results if r.get("tier", "impl") == tier]
        summary["by_tier"][tier] = {
            "pass": sum(1 for x in rs if x.get("passed")), "of": len(rs),
            "rate": round(sum(1 for x in rs if x.get("passed")) / max(len(rs), 1), 3)}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{args.label}-{stamp}.json"
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))

    print("\n" + "=" * 66)
    print(f"PASS RATE      {summary['passed']}/{summary['jobs']} = {summary['pass_rate']:.1%}")
    for tier, v in summary["by_tier"].items():
        print(f"  tier {tier:<6} {v['pass']}/{v['of']} = {v['rate']:.1%}")
    print(f"OVERCLAIM      {len(overclaims)}/{summary['jobs']} = {summary['overclaim_rate']:.1%} "
          f"(said DONE, hidden test failed)")
    print(f"MEDIAN WALL    {summary['median_wall_s']}s     TOTAL {total_wall}s")
    print(f"saved -> {path}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
