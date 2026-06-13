# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Run the standardized eval pack against a live agent and publish deltas.

Fixed prompts + deterministic scoring (evals/eval_pack.py + evals/scorer.py), so
progress is measured the same way every time. Talks to the agent over HTTP (the
in-process /api/agent/nfet/run), so it can run on the box against the live model.

Usage (on the box):
    PYTHONPATH=. .venv/bin/python scripts/run_eval_pack.py \
        --reasoner workers_ai --out artifacts/eval-pack/2026-06-13-2030
    # optional: --limit 6  --category math_trap  --prev <prior>/results.jsonl

Retrieval-trap prompts need seeded memory to fully pass; without it they test
non-fabrication. The report says so rather than hiding it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evals.eval_pack import PROMPTS          # noqa: E402
from evals.scorer import score_prompt, rollup  # noqa: E402


def run_one(base, entry, reasoner, timeout):
    body = {
        "command": entry["prompt"], "reasoner": reasoner,
        "max_segments": 2, "segment_tokens": 80, "final_tokens": 220,
        "max_verifies": 1, "max_retrieves": 1,
    }
    req = urllib.request.Request(base + "/api/agent/nfet/run",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:7866")
    ap.add_argument("--reasoner", default="workers_ai")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--category", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prev", default="")
    ap.add_argument("--timeout", type=float, default=180)
    args = ap.parse_args()

    prompts = [p for p in PROMPTS if not args.category or p["category"] == args.category]
    if args.limit:
        prompts = prompts[:args.limit]
    os.makedirs(args.out, exist_ok=True)

    scores, rows = [], []
    for i, entry in enumerate(prompts, 1):
        t0 = time.time()
        try:
            result = run_one(args.base, entry, args.reasoner, args.timeout)
            sc = score_prompt(entry, result)
            sc["model_used"] = (result.get("receipt") or {}).get("model_used")
            sc["seconds"] = round(time.time() - t0, 1)
        except Exception as exc:
            sc = {"id": entry["id"], "category": entry["category"], "status": "error",
                  "reasons": [str(exc)[:140]], "seconds": round(time.time() - t0, 1)}
        scores.append(sc)
        rows.append(sc)
        print(f"[{i}/{len(prompts)}] {entry['id']:10s} {sc['status']:8s} "
              f"{sc['category']:22s} {';'.join(sc.get('reasons', []))[:70]}", flush=True)

    rep = rollup(scores)
    with open(os.path.join(args.out, "results.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    prev = {}
    if args.prev and os.path.exists(args.prev):
        with open(args.prev) as f:
            for line in f:
                d = json.loads(line)
                prev[d["id"]] = d["status"]

    lines = [f"# Eval pack report ({len(scores)} prompts, reasoner={args.reasoner})", ""]
    t = rep["totals"]
    lines.append(f"**Totals:** pass {t['pass']} · partial {t['partial']} · fail {t['fail']} · "
                 f"error {t.get('error',0)} · skip {t['skip']}")
    lines.append("")
    lines.append("| category | pass | partial | fail |")
    lines.append("|---|---|---|---|")
    for c, v in sorted(rep["by_category"].items()):
        lines.append(f"| {c} | {v['pass']} | {v['partial']} | {v['fail']} |")
    if prev:
        deltas = [f"- {r['id']}: {prev[r['id']]} → {r['status']}"
                  for r in rows if r["id"] in prev and prev[r["id"]] != r["status"]]
        lines += ["", f"## Deltas vs previous ({len(deltas)} changed)"] + (deltas or ["- none"])
    fails = [f"- {r['id']} ({r['category']}): {';'.join(r.get('reasons', []))}"
             for r in rows if r["status"] in ("fail", "error")]
    lines += ["", f"## Failures ({len(fails)})"] + (fails or ["- none"])
    with open(os.path.join(args.out, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines[:6]))
    print(f"\nwrote {args.out}/results.jsonl + report.md")


if __name__ == "__main__":
    main()
