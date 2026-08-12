#!/usr/bin/env python3
"""Reproducible hidden-test benchmark for customer-facing terminal agents.

This runner launches every agent in a fresh temporary directory. The grading
file is created only after the agent exits, so an agent cannot read, edit, or
delete its own test. Raw process output, file hashes, timings, and grader output
are retained as receipts. A single run is a pilot, not a leaderboard claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bench.tasks import TASKS  # noqa: E402

DEFAULT_TASKS = (
    "iso_duration",
    "semver",
    "expr_eval",
    "jsonpath",
    "fix_multifile_stats",
    "fix_state_machine",
)
HIDDEN = "_lolm_hidden_check.py"
CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex"
LOLM_SOURCE = str(ROOT / "clients" / "cli" / "bin" / "lolm.mjs")

# The controlled comparison: LOLM and Google's own CLI driving the identical
# model, so a score difference is a difference between the two scaffolds rather
# than between two model vendors.
CONTROL_MODEL = os.environ.get("LOLM_BENCH_GEMINI_MODEL", "gemini-3.1-flash-lite")
GROQ_MODEL = os.environ.get("LOLM_BENCH_GROQ_MODEL", "llama-3.3-70b-versatile")
# The default local model shares the machine with the 4B NFET controller. On a
# memory-constrained host a 14B model and the controller thrash together, so the
# ablation model is overridable and defaults small enough to co-reside.
LOCAL_MODEL = os.environ.get("LOLM_BENCH_LOCAL_MODEL", "qwen3:14b")

LOLM_TRACKS = {
    "lolm": ("ollama", LOCAL_MODEL, True, f"Ollama {LOCAL_MODEL} (local)"),
    "lolm_nonfet": ("ollama", LOCAL_MODEL, False, f"Ollama {LOCAL_MODEL} (local), NFET disabled (ablation)"),
    "lolm_cerebras": ("cerebras", "gpt-oss-120b", True, "Cerebras gpt-oss-120b via user-owned key"),
    "lolm_cerebras_nonfet": ("cerebras", "gpt-oss-120b", False, "Cerebras gpt-oss-120b, NFET disabled (ablation)"),
    "lolm_gemini": ("google", CONTROL_MODEL, True, f"Google {CONTROL_MODEL} via user-owned key"),
    "lolm_gemini_nonfet": ("google", CONTROL_MODEL, False, f"Google {CONTROL_MODEL}, NFET disabled (ablation)"),
    "lolm_groq": ("groq", GROQ_MODEL, True, f"Groq {GROQ_MODEL} via user-owned key"),
    "lolm_groq_nonfet": ("groq", GROQ_MODEL, False, f"Groq {GROQ_MODEL}, NFET disabled (ablation)"),
}
CLI_BACKENDS = {
    "codex": "installed Codex CLI with its own local configuration",
    "gemini": f"installed Gemini CLI on {CONTROL_MODEL} via user-owned key",
    "claude": "installed Claude Code CLI with its own local credentials",
}

# Rate-limited hosted backends need a gap between trials or the harness measures
# the provider's throttle instead of the agent.
COOLDOWN_AGENTS = {"lolm_cerebras", "lolm_cerebras_nonfet", "lolm_gemini", "lolm_gemini_nonfet",
                   "lolm_groq", "lolm_groq_nonfet", "gemini"}


def gemini_api_key() -> str:
    """Resolve the Gemini credential without ever storing one in this repo."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    if sys.platform == "darwin":
        found = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
             "-s", "lolm-cli-provider:google", "-w"],
            text=True, capture_output=True, check=False,
        )
        if found.returncode == 0:
            return found.stdout.strip()
    return ""


def sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def run_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
        return (result.stdout or result.stderr).strip().splitlines()[-1][:300]
    except Exception as exc:  # provenance should not abort the actual benchmark
        return f"unavailable: {type(exc).__name__}: {exc}"


def git_value(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], text=True, capture_output=True, check=False)
    return result.stdout.strip()


def file_manifest(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == HIDDEN or ".git" in path.parts:
            continue
        body = path.read_bytes()
        rows.append({"path": str(path.relative_to(root)), "bytes": len(body), "sha256": sha(body)})
    return rows


def task_digest(task: dict[str, Any]) -> dict[str, Any]:
    seed = json.dumps(task.get("seed") or {}, sort_keys=True, separators=(",", ":"))
    return {
        "id": task["id"],
        "tier": task.get("tier", "impl"),
        "instruction_sha256": sha(task["task"]),
        "hidden_test_sha256": sha(task["test"]),
        "seed_sha256": sha(seed),
    }


def prompt_for(task: dict[str, Any]) -> str:
    return (
        f"{task['task']}\n\n"
        "Benchmark rules: work only in the current directory; do not use the network; "
        "do not install dependencies; use only the Python standard library; inspect any "
        "seed files before editing; implement the requested result and verify it. A hidden "
        "grader will run only after you stop."
    )


def agent_command(agent: str, prompt: str, work: Path, *, nfet: bool, max_steps: int) -> list[str]:
    if agent in LOLM_TRACKS:
        provider, model, track_nfet, _ = LOLM_TRACKS[agent]
        command = [
            shutil.which("node") or "node",
            LOLM_SOURCE,
            "run",
            prompt,
            "--cwd",
            str(work),
            "--mode",
            "trusted",
            "--yes",
            "--json",
            "--max-steps",
            str(max_steps),
            "--provider",
            provider,
            "--model",
            model,
        ]
        # An explicit ablation track always wins over the run-wide default, so
        # the NFET-off row stays honest even when the run enables NFET.
        if not (nfet and track_nfet):
            command.append("--no-nfet")
        return command
    if agent == "gemini":
        return [
            shutil.which("gemini") or "gemini",
            "-p", prompt,
            "-m", CONTROL_MODEL,
            "--yolo",
            "--skip-trust",
            "-o", "json",
        ]
    if agent == "claude":
        return [
            shutil.which("claude") or "claude",
            "-p", prompt,
            "--permission-mode", "bypassPermissions",
            "--output-format", "json",
        ]
    if agent == "codex":
        return [
            CODEX,
            "exec",
            "--cd",
            str(work),
            "--approve-for-me",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-rules",
            "--json",
            prompt,
        ]
    raise ValueError(f"unknown agent: {agent}")


def execute(command: list[str], *, cwd: Path, timeout: int, env: dict[str, str]) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    tick = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "started_at": started.isoformat(),
            "wall_seconds": round(time.monotonic() - tick, 3),
            "exit_code": result.returncode,
            "timed_out": False,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "started_at": started.isoformat(),
            "wall_seconds": round(time.monotonic() - tick, 3),
            "exit_code": 124,
            "timed_out": True,
            "stdout": (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            "stderr": (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
        }


def grade(task: dict[str, Any], work: Path) -> dict[str, Any]:
    (work / HIDDEN).write_text(task["test"])
    try:
        result = subprocess.run(
            [sys.executable, HIDDEN], cwd=work, text=True, capture_output=True, timeout=30, check=False
        )
        return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired as exc:
        return {"exit_code": 124, "stdout": exc.stdout or "", "stderr": exc.stderr or "grader timed out"}
    finally:
        (work / HIDDEN).unlink(missing_ok=True)


def save_text(path: Path, value: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}


def classify_infrastructure(text: str) -> str | None:
    """Name the blocker when a run never reached the model, so it is excluded
    rather than scored as a model failure."""
    lower = text.lower()
    # Providers phrase a throttle a dozen ways, and the underscore form of the
    # LOLM error code ("rate_limited") does not contain the space in "rate
    # limit". Normalise separators so one set of needles catches them all.
    flat = lower.replace("_", " ").replace("-", " ")
    limit_needles = (
        "usage limit", "rate limit", "rate limited", "quota", "429",
        "limit exceeded", "tokens per day", "per day limit", "daily limit",
        "too many tokens", "too many requests", "capacity", "overloaded",
    )
    if any(needle in flat for needle in limit_needles):
        return "usage_limit"
    if "not logged in" in lower or "please run /login" in lower or "auth" in lower and "api key" in lower:
        return "auth"
    if "api key not valid" in lower or "set an auth method" in lower or "credential" in lower:
        return "auth"
    return None


def parse_agent_output(agent: str, stdout: str, stderr: str = "") -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if agent == "gemini":
        blob = stdout.strip()
        try:
            payload = json.loads(blob)
        except Exception:
            return {"parsed": False, "infrastructure_error": classify_infrastructure(stdout + stderr) or "unparseable_output"}
        error = json.dumps(payload.get("error") or "")
        stats = (payload.get("stats") or {}).get("tools") or {}
        return {
            "parsed": True,
            "model": CONTROL_MODEL,
            "tool_calls": stats.get("totalCalls"),
            "tool_failures": stats.get("totalFail"),
            "usage": (payload.get("stats") or {}).get("models"),
            "error": payload.get("error") or None,
            "infrastructure_error": classify_infrastructure(error + stderr) if payload.get("error") else None,
        }
    if agent == "claude":
        try:
            payload = json.loads(stdout.strip())
        except Exception:
            return {"parsed": False, "infrastructure_error": classify_infrastructure(stdout + stderr) or "unparseable_output"}
        error = str(payload.get("result") or "") if payload.get("is_error") else ""
        return {
            "parsed": True,
            "model": payload.get("model"),
            "usage": payload.get("usage"),
            "error": error or None,
            "infrastructure_error": classify_infrastructure(error + stderr) if error else None,
        }
    if agent.startswith("lolm"):
        try:
            payload = json.loads(lines[-1])
        except Exception:
            return {"parsed": False, "infrastructure_error": "unparseable_output"}
        nfet = payload.get("nfet") or {}
        failure = json.dumps(payload.get("error") or "") if not payload.get("ok") else ""
        return {
            "parsed": True,
            "infrastructure_error": classify_infrastructure(failure) if failure else None,
            "ok": payload.get("ok"),
            "provider": payload.get("provider"),
            "model": payload.get("model"),
            "verified": payload.get("verified"),
            "steps": payload.get("steps"),
            "usage": payload.get("usage"),
            "nfet": {key: nfet.get(key) for key in ("available", "text_sha256", "head_trained", "checkpoint", "verified", "decision", "telemetry") if key in nfet},
            "error": payload.get("error"),
        }
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    messages = [str(event.get("message") or event.get("error", {}).get("message") or "") for event in events if event.get("type") in {"error", "turn.failed"}]
    error = next((message for message in messages if message), "")
    lower = error.lower()
    infrastructure = "usage_limit" if "usage limit" in lower else "auth" if "auth" in lower or "log in" in lower else None
    completed = next((event for event in reversed(events) if event.get("type") == "turn.completed"), {})
    return {"parsed": bool(events), "usage": completed.get("usage"), "error": error or None, "infrastructure_error": infrastructure}


def run_trial(
    agent: str,
    task: dict[str, Any],
    trial: int,
    results: Path,
    *,
    timeout: int,
    nfet: bool,
    max_steps: int = 12,
) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix=f"lolm-bench-{agent}-{task['id']}-"))
    try:
        for relative, content in (task.get("seed") or {}).items():
            target = work / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        command = agent_command(agent, prompt_for(task), work, nfet=nfet, max_steps=max_steps)
        env = dict(os.environ)
        env["NO_COLOR"] = "1"
        if agent == "gemini":
            key = gemini_api_key()
            if key:
                env["GEMINI_API_KEY"] = key
        process = execute(command, cwd=work, timeout=timeout, env=env)
        agent_receipt = parse_agent_output(agent, process["stdout"], process["stderr"])
        before_grade = file_manifest(work)
        grader = grade(task, work)
        raw = results / "raw" / agent / f"{task['id']}-trial-{trial}"
        stdout = save_text(raw / "agent.stdout.txt", process.pop("stdout"))
        stderr = save_text(raw / "agent.stderr.txt", process.pop("stderr"))
        grade_out = save_text(raw / "grader.stdout.txt", grader.pop("stdout"))
        grade_err = save_text(raw / "grader.stderr.txt", grader.pop("stderr"))
        artifact_dir = results / "artifacts" / agent / f"{task['id']}-trial-{trial}"
        shutil.copytree(work, artifact_dir, dirs_exist_ok=True)
        passed = grader["exit_code"] == 0
        return {
            "agent": agent,
            "task": task["id"],
            "tier": task.get("tier", "impl"),
            "trial": trial,
            "passed": passed,
            "scoreable": not bool(agent_receipt.get("infrastructure_error")),
            "agent_receipt": agent_receipt,
            "agent_process": process,
            "grader": grader,
            "receipts": {"stdout": stdout, "stderr": stderr, "grader_stdout": grade_out, "grader_stderr": grade_err},
            "output_files": before_grade,
            "artifact_path": str(artifact_dir),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_report(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# LOLM customer CLI cross-agent benchmark",
        "",
        f"Run ID: `{payload['run_id']}`",
        f"Generated: `{payload['created_at']}`",
        f"Commit: `{payload['environment']['git_commit']}`",
        f"Working tree dirty at launch: `{payload['environment']['git_dirty']}`",
        "",
        "## Score",
        "",
        "| Agent | Backend/model | Passed | Pass rate | Median wall time |",
        "|---|---|---:|---:|---:|",
    ]
    for name, summary in payload["summary"].items():
        rate = f"{summary['pass_rate']:.1%}" if summary["pass_rate"] is not None else "UNSCORED"
        score = f"{summary['passed']}/{summary['scoreable_jobs']}" if summary["scoreable_jobs"] else f"0/0 ({summary['excluded']} excluded)"
        lines.append(
            f"| {name} | {summary['backend']} | {score} | "
            f"{rate} | {summary['median_wall_seconds']:.1f}s |"
        )
    lines += ["", "## Task receipts", "", "| Task | Tier | " + " | ".join(payload["agents"]) + " |", "|---|---|" + "---|" * len(payload["agents"])]
    keyed = {(row["agent"], row["task"]): row for row in payload["results"]}
    for task in payload["tasks"]:
        cells = []
        for agent in payload["agents"]:
            row = keyed.get((agent, task["id"]))
            cells.append("UNSCORED" if row and not row.get("scoreable", True) else "PASS" if row and row["passed"] else "FAIL")
        lines.append(f"| {task['id']} | {task['tier']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Method",
        "",
        "Each agent received the same task text and seed files in a fresh temporary directory. The hidden grader file did not exist until after the agent process exited. Grader exit code 0 is the only pass condition. Timeouts, raw stdout/stderr, grader output, artifact copies, and SHA-256 file hashes are retained beside this report.",
        "",
        "LOLM rows measure the same customer CLI and tool runtime with the backend named in the score table. NFET status for this run is recorded in `results.json`; NFET is a trajectory controller and does not change the underlying model's raw knowledge. Codex uses the authenticated installed CLI and the model configured in the local Codex settings.",
        "",
        "## Interpretation limits",
        "",
        "This is a local product acceptance pilot, not an official SWE-bench or Terminal-Bench submission. A single trial per task has high variance and cannot establish broad superiority. Public frontier results must only be compared on their original harnesses. Runs blocked by authentication, quota, or provider infrastructure are marked UNSCORED rather than counted as model failures. Claude Code and Gemini CLI were not scored because no authenticated runnable Claude installation or Gemini credential was available during this run.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "python3 bench/validate.py",
        f"python3 bench/customer_cli/run_cross_agent.py --agents {','.join(payload['agents'])} --lolm-nfet",
        "```",
    ]
    path.write_text("\n".join(lines) + "\n")


def summarize(payload: dict[str, Any]) -> None:
    payload["summary"] = {}
    for agent in payload["agents"]:
        rows = [row for row in payload["results"] if row["agent"] == agent]
        scoreable = [row for row in rows if row.get("scoreable", True)]
        passed = sum(bool(row["passed"]) for row in scoreable)
        payload["summary"][agent] = {
            "backend": payload["environment"].get(f"{agent}_backend", "unknown"),
            "passed": passed,
            "jobs": len(rows),
            "scoreable_jobs": len(scoreable),
            "excluded": len(rows) - len(scoreable),
            "pass_rate": passed / len(scoreable) if scoreable else None,
            "median_wall_seconds": statistics.median(row["agent_process"]["wall_seconds"] for row in rows) if rows else 0,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", default="lolm,codex")
    parser.add_argument("--tasks", default="", help="comma-separated task ids; defaults to --suite")
    parser.add_argument("--suite", default="full", choices=("full", "pilot"),
                        help="full = every task in bench.tasks; pilot = the original six-task set")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=480)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--lolm-nfet", action="store_true")
    parser.add_argument("--provider-cooldown", type=int, default=20)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rebuild", type=Path, help="reclassify and rebuild an existing results.json from raw receipts")
    args = parser.parse_args()
    if args.rebuild:
        source = args.rebuild.resolve()
        payload = json.loads(source.read_text())
        for row in payload["results"]:
            stdout = Path(row["receipts"]["stdout"]["path"]).read_text()
            stderr = Path(row["receipts"]["stderr"]["path"]).read_text()
            receipt = parse_agent_output(row["agent"], stdout, stderr)
            row["agent_receipt"] = receipt
            row["scoreable"] = not bool(receipt.get("infrastructure_error"))
        summarize(payload)
        source.write_text(json.dumps(payload, indent=2) + "\n")
        write_report(payload, source.with_name("REPORT.md"))
        print(source.parent)
        return 0
    agents = [value.strip() for value in args.agents.split(",") if value.strip()]
    default_tasks = [task["id"] for task in TASKS] if args.suite == "full" else list(DEFAULT_TASKS)
    requested = [value.strip() for value in args.tasks.split(",") if value.strip()] or default_tasks
    by_id = {task["id"]: task for task in TASKS}
    missing = [task for task in requested if task not in by_id]
    if missing:
        raise SystemExit(f"unknown tasks: {', '.join(missing)}")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or ROOT / "bench" / "customer_cli" / "results" / run_id).resolve()
    output.mkdir(parents=True, exist_ok=False)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
        "tasks": [task_digest(by_id[name]) for name in requested],
        "settings": {"repeat": args.repeat, "timeout_seconds": args.timeout, "max_steps": args.max_steps, "lolm_nfet": args.lolm_nfet, "provider_cooldown_seconds": args.provider_cooldown},
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "git_commit": git_value("rev-parse", "HEAD"),
            "git_dirty": bool(git_value("status", "--porcelain")),
            "lolm_version": run_version([shutil.which("node") or "node", LOLM_SOURCE, "--version"]),
            "codex_version": run_version([CODEX, "--version"]),
            "gemini_version": run_version([shutil.which("gemini") or "gemini", "--version"]),
            "claude_version": run_version([shutil.which("claude") or "claude", "--version"]),
            "control_model": CONTROL_MODEL,
            **{f"{name}_backend": label for name, (_, _, _, label) in LOLM_TRACKS.items()},
            **{f"{name}_backend": label for name, label in CLI_BACKENDS.items()},
        },
        "results": [],
    }
    for agent in agents:
        for task_id in requested:
            for trial in range(1, args.repeat + 1):
                print(f"[{agent}] {task_id} trial {trial}/{args.repeat}", flush=True)
                row = run_trial(agent, by_id[task_id], trial, output, timeout=args.timeout,
                                nfet=args.lolm_nfet, max_steps=args.max_steps)
                payload["results"].append(row)
                (output / "results.partial.json").write_text(json.dumps(payload, indent=2) + "\n")
                blocker = row["agent_receipt"].get("infrastructure_error")
                verdict = f"UNSCORED ({blocker})" if blocker else "PASS" if row["passed"] else "FAIL"
                print(f"  {verdict} in {row['agent_process']['wall_seconds']}s", flush=True)
                if agent in COOLDOWN_AGENTS and args.provider_cooldown > 0:
                    time.sleep(args.provider_cooldown)
    summarize(payload)
    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    (output / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    (output / "results.partial.json").unlink(missing_ok=True)
    write_report(payload, output / "REPORT.md")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
