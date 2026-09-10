#!/usr/bin/env python3
"""Build one evidence report from one or more benchmark runs.

The numbers in the report are read out of the run artifacts rather than typed in
by hand, so the document cannot drift from what actually happened. Every claim it
makes is traceable to a `results.json` whose SHA-256 it prints.

Runs are reported separately. Two runs may share an agent name — the same track
run on a different day — and folding their rows together would turn two
experiments into one that never happened. A controlled comparison is only ever
made between rows of the same run.

    python3 bench/customer_cli/make_evidence.py RESULTS...  --out EVIDENCE.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Only a pair sharing one model isolates the scaffold; anything else mostly
# measures whichever model is stronger, so the report must not imply otherwise.
# The nonfet pairs share the model AND the scaffold, isolating the NFET
# controller alone — the cleanest ablation the suite can produce.
CONTROLLED_PAIRS = [
    ("lolm", "lolm_nonfet"),
    ("lolm_cerebras", "lolm_cerebras_nonfet"),
    ("lolm_groq", "lolm_groq_nonfet"),
    ("lolm_openrouter", "lolm_openrouter_nonfet"),
    ("lolm_gemini", "lolm_gemini_nonfet"),
    ("lolm_gemini", "gemini"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(paths: list[Path]) -> list[dict[str, Any]]:
    runs = []
    for path in paths:
        payload = json.loads(path.read_text())
        payload["_path"] = path
        payload["_sha256"] = sha256(path)
        payload["_partial"] = path.name.endswith("partial.json") or "completed_at" not in payload
        runs.append(payload)
    return runs


def score(rows: list[dict[str, Any]], run: dict[str, Any]) -> dict[str, Any]:
    scoreable = [row for row in rows if row.get("scoreable", True)]
    passed = sum(1 for row in scoreable if row["passed"])
    excluded: dict[str, int] = {}
    for row in rows:
        if not row.get("scoreable", True):
            blocker = row["agent_receipt"].get("infrastructure_error") or "unknown"
            excluded[blocker] = excluded.get(blocker, 0) + 1
    return {
        "attempted": len(rows),
        "scored": len(scoreable),
        "passed": passed,
        "rate": passed / len(scoreable) if scoreable else None,
        "median_seconds": statistics.median([row["agent_process"]["wall_seconds"] for row in rows]) if rows else 0.0,
        "excluded": excluded,
        "backend": run["environment"].get(f"{rows[0]['agent']}_backend", "unknown") if rows else "unknown",
    }


def nfet_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    receipts = [row["agent_receipt"].get("nfet") or {} for row in rows]
    live = [receipt for receipt in receipts if receipt.get("available")]
    decisions: dict[str, int] = {}
    for receipt in live:
        label = (receipt.get("decision") or {}).get("label") if isinstance(receipt.get("decision"), dict) else receipt.get("decision")
        if label:
            decisions[label] = decisions.get(label, 0) + 1
    return {
        "runs_with_live_controller": len(live),
        "trained_head": sum(1 for receipt in live if receipt.get("head_trained")),
        "decisions": dict(sorted(decisions.items(), key=lambda item: -item[1])),
    }


def cell(row: dict[str, Any] | None) -> str:
    if row is None:
        return "–"
    if not row.get("scoreable", True):
        return f"UNSCORED[^{row['agent_receipt'].get('infrastructure_error', 'blocked')}]"
    return "PASS" if row["passed"] else "FAIL"


def effort(agent: str, shared: list[str], keyed: dict) -> tuple[float, int]:
    rows = [keyed[(agent, task)] for task in shared]
    steps = [r["agent_receipt"].get("steps") for r in rows if isinstance(r["agent_receipt"].get("steps"), int)]
    pokes = [r["agent_receipt"].get("interventions") for r in rows if isinstance(r["agent_receipt"].get("interventions"), int)]
    return (sum(steps) / len(steps) if steps else 0.0, sum(pokes) if pokes else 0)


def compare(left: str, right: str, tasks: list[str], keyed: dict, scores: dict) -> list[str]:
    # Head to head only counts tasks BOTH sides actually attempted. A task one
    # side never reached is not a win for the other side.
    shared = [
        task for task in tasks
        if keyed.get((left, task), {}).get("scoreable", False)
        and keyed.get((right, task), {}).get("scoreable", False)
    ]
    if not shared:
        return []
    left_only = sum(1 for task in shared if keyed[(left, task)]["passed"] and not keyed[(right, task)]["passed"])
    right_only = sum(1 for task in shared if keyed[(right, task)]["passed"] and not keyed[(left, task)]["passed"])
    left_passed = sum(1 for task in shared if keyed[(left, task)]["passed"])
    right_passed = sum(1 for task in shared if keyed[(right, task)]["passed"])
    verdict = ("a tie" if left_only == right_only
               else f"`{left}` ahead by {left_only - right_only}" if left_only > right_only
               else f"`{right}` ahead by {right_only - left_only}")
    # An ablation pairs the same scaffold on the same model with only the
    # controller toggled, so it measures NFET alone rather than a vendor.
    ablation = right.endswith("_nonfet") and right.startswith(left)
    heading = (f"NFET ablation — **`{left}` (controller on) vs `{right}` (controller off)**"
               if ablation else f"**`{left}` vs `{right}`**")
    lines = [
        f"{heading} on the {len(shared)} tasks both attempted: **{left_passed}–{right_passed}**, {verdict}. "
        f"`{left}` solved {left_only} that `{right}` missed; `{right}` solved {right_only} that `{left}` missed.",
        "",
    ]
    median_left, median_right = scores[left]["median_seconds"], scores[right]["median_seconds"]
    if ablation:
        # An ablation is not only about pass rate: a controller that keeps the
        # score but spends more turns or time to get there is a cost.
        left_steps, left_pokes = effort(left, shared, keyed)
        right_steps, _ = effort(right, shared, keyed)
        lines += [
            f"Cost of running the controller: {left_steps:.1f} steps per task against {right_steps:.1f} without it, "
            f"{left_pokes} intervention(s) issued, median wall time {median_left:.0f}s against {median_right:.0f}s.",
            "",
        ]
    else:
        unscored_left = scores[left]["attempted"] - scores[left]["scored"]
        unscored_right = scores[right]["attempted"] - scores[right]["scored"]
        lines += [
            f"Outside that shared set, `{left}` was blocked on {unscored_left} task(s) and `{right}` on "
            f"{unscored_right}. Those are excluded from the head-to-head in both directions: a task an agent "
            f"never reached is not a loss for it and not a win for anyone else, so whole-suite rates in the "
            f"scorecard are over different task sets and are not comparable to each other.",
            "",
        ]
    return lines


def report_run(run: dict[str, Any]) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in run["results"]:
        grouped.setdefault(row["agent"], []).append(row)
    agents = list(grouped)
    scores = {agent: score(rows, run) for agent, rows in grouped.items()}
    tasks = [task["id"] for task in run["tasks"]]
    tiers = {task["id"]: task["tier"] for task in run["tasks"]}
    keyed = {(row["agent"], row["task"]): row for rows in grouped.values() for row in rows}
    environment = run["environment"]
    settings = run.get("settings", {})
    marker = " (partial)" if run["_partial"] else ""
    when = str(run.get("created_at", ""))[:10]

    lines = [
        f"## Run `{run['run_id']}`{marker}",
        "",
        f"{when} · commit `{environment.get('git_commit', '')[:10]}` · working tree dirty: {environment.get('git_dirty')} · "
        f"{len(tasks)} task(s) · {settings.get('repeat', '?')} trial(s) per task",
        "",
        "| Track | Backend | Passed | Pass rate | Median wall | Excluded |",
        "|---|---|---:|---:|---:|---|",
    ]
    for agent in agents:
        row = scores[agent]
        rate = f"{row['rate']:.0%}" if row["rate"] is not None else "n/a"
        excluded = ", ".join(f"{count}× {name}" for name, count in row["excluded"].items()) or "—"
        lines.append(f"| `{agent}` | {row['backend']} | {row['passed']}/{row['scored']} | {rate} | {row['median_seconds']:.0f}s | {excluded} |")

    comparisons: list[str] = []
    for left, right in CONTROLLED_PAIRS:
        if left in scores and right in scores and scores[left]["scored"] and scores[right]["scored"]:
            comparisons += compare(left, right, tasks, keyed, scores)
    if comparisons:
        lines += ["", "### Controlled comparisons", ""] + comparisons

    lines += ["### Per-task results", "", "| Task | Tier | " + " | ".join(f"`{a}`" for a in agents) + " |",
              "|---|---|" + "---|" * len(agents)]
    for task in tasks:
        lines.append(f"| `{task}` | {tiers.get(task, '?')} | " + " | ".join(cell(keyed.get((agent, task))) for agent in agents) + " |")

    controller = []
    for agent in agents:
        if not agent.startswith("lolm"):
            continue
        summary = nfet_summary(grouped[agent])
        if not summary["runs_with_live_controller"]:
            controller.append(f"- `{agent}`: controller not active in any run.")
            continue
        decisions = ", ".join(f"{label} ×{count}" for label, count in summary["decisions"].items()) or "none recorded"
        controller.append(
            f"- `{agent}`: live controller on {summary['runs_with_live_controller']} runs, "
            f"trained head on {summary['trained_head']}; final decisions: {decisions}."
        )
    if controller:
        lines += ["", "### NFET controller", ""] + controller
    lines.append("")
    return lines


def build(runs: list[dict[str, Any]]) -> str:
    lines = [
        f"# LOLM benchmark evidence — {datetime.now(timezone.utc).date().isoformat()}",
        "",
        "Generated by `bench/customer_cli/make_evidence.py` from the run artifacts named",
        "at the bottom. Every number here is read out of those files. Each run is",
        "reported on its own; rows from different runs are never combined.",
        "",
    ]
    for run in runs:
        lines += report_run(run)
    lines += [
        "## Method",
        "",
        "Each agent got the same task text and seed files in a fresh temporary directory.",
        "The hidden grader was written only after the agent process exited, so no agent",
        "could read, weaken, or delete the test it was scored on. Grader exit code 0 is",
        "the only pass condition. `bench/validate.py` separately proves each hidden test",
        "passes against a reference implementation and fails against the seeded bug.",
        "",
        "A run blocked before it reached a model — missing credential, expired login,",
        "exhausted quota — is recorded as UNSCORED with the blocker named and excluded",
        "from the rate. Reporting an agent that never ran as 0% would be dishonest.",
        "",
        "## What this does not show",
        "",
        "This is a local acceptance benchmark. Its percentages are not comparable with",
        "SWE-bench Verified or Terminal-Bench numbers: different tasks, different sandbox,",
        "different scaffold configuration. No public leaderboard figure is reproduced here",
        "as though it were measured on this suite.",
        "",
        "Only a pair sharing one model isolates the agent scaffold, and only a pair",
        "sharing model and scaffold isolates the controller. A cross-vendor row largely",
        "reflects which model is stronger.",
        "",
        "A single trial has high variance; small gaps between tracks are not meaningful",
        "without repeats.",
        "",
        "## Provenance",
        "",
        "| Run | Tasks | Trials | Commit | Dirty | SHA-256 of results |",
        "|---|---:|---:|---|---|---|",
    ]
    for run in runs:
        environment = run["environment"]
        settings = run.get("settings", {})
        marker = " (partial)" if run["_partial"] else ""
        lines.append(
            f"| `{run['run_id']}`{marker} | {len(run['tasks'])} | {settings.get('repeat', '?')} | "
            f"`{environment.get('git_commit', '')[:10]}` | {environment.get('git_dirty')} | `{run['_sha256'][:32]}…` |"
        )
    lines += ["", "Versions recorded at launch:", ""]
    seen: set[str] = set()
    for run in runs:
        for key, value in run["environment"].items():
            if key.endswith("_version") and value and key not in seen:
                seen.add(key)
                lines.append(f"- `{key.removesuffix('_version')}`: {value}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--notes", type=Path,
                        help="markdown appended verbatim under Caveats; narrative belongs here so "
                             "the derived numbers above stay derived")
    args = parser.parse_args()
    report = build(load(args.results))
    if args.notes:
        report += "\n## Caveats recorded by hand\n\n" + args.notes.read_text().strip() + "\n"
    args.out.write_text(report)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
