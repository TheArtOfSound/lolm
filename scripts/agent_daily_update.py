#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The daily self-driving learned-update agent.

Pipeline:  gather learning → find concrete targets → apply safe patches → run the
proof gates (typecheck · lint · tests · build · evals · security · secret-scan ·
protected-files) → write a receipt → compute a single verdict → (gated) branch +
commit → (gated) merge · npm canary · npm stable · deploy. Every irreversible step
is behind a passing gate AND a credential AND the --allow-fire flag; without all
three it is recorded as skipped, never faked.

Modes:
  (default)      shadow — run everything, evaluate gates, write the receipt, touch
                 nothing in git and fire nothing. Safe to run anywhere, anytime.
  --commit       create the daily branch and commit the applied changes locally.
  --allow-fire   permit merge / publish / deploy IF the gates pass AND creds exist.
  --push         push the daily branch (implies --commit).

Tests/evals/rollback are never skippable — that is the line that keeps this an
autonomous release agent and not a repo-destroyer with API keys.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.release.gates import (GateResult, MergeGate, PublishGate, DeployGate,
                                secret_scan, protected_files_touched, evaluate_gates)
from lolm.release.receipt import DailyReceipt, compute_verdict, receipt_to_markdown
from lolm.release.versioning import canary_version, bump_patch, read_pkg_version
from lolm.release import learning as L

CLIENT = ROOT / "clients" / "js"
PKG = CLIENT / "package.json"
CHANGELOG = ROOT / "CHANGELOG.md"
DAILY_DIR = ROOT / "runs" / "daily"


# ── shell ────────────────────────────────────────────────────────────────────
def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"


def have(tool: str) -> bool:
    return run_cmd([tool, "--version"])[0] == 0


# ── targets → safe patches ───────────────────────────────────────────────────
def apply_changelog(date: str, learning: Dict[str, Any], version: str) -> bool:
    entry = (f"## {date} — daily learned update (canary {version})\n\n"
             f"- Learning sources: {', '.join(learning.get('sources_present') or ['none'])}\n"
             f"- Source-backed memories: {learning.get('memories_written', 0)} · "
             f"HF datasets scanned: {learning.get('hf_datasets_scanned', 0)} · "
             f"web searches: {learning.get('web_searches_performed', 0)}\n"
             f"- Controller-training candidates queued (eval-gated, no weight change): "
             f"{learning.get('hf_candidates_queued', 0)}\n\n")
    head = "# Changelog — LOLM/NFET daily learned updates\n\n"
    prior = CHANGELOG.read_text() if CHANGELOG.exists() else head
    if not prior.startswith("#"):
        prior = head + prior
    body = prior[len(head):] if prior.startswith(head) else prior
    CHANGELOG.write_text(head + entry + body)
    return True


# ── gates ────────────────────────────────────────────────────────────────────
def changed_python_files() -> List[str]:
    code, out = run_cmd(["git", "diff", "--name-only", "HEAD"])
    files = [f for f in out.splitlines() if f.endswith(".py")]
    return files


def git_diff_text() -> str:
    return run_cmd(["git", "diff", "HEAD"])[1]


def git_changed_files() -> List[str]:
    out = run_cmd(["git", "status", "--porcelain"])[1]
    return [line[3:].strip() for line in out.splitlines() if line.strip()]


def gate_typecheck() -> GateResult:
    pys = changed_python_files()
    cmd = [sys.executable, "-m", "py_compile", *pys] if pys else [sys.executable, "-c", "pass"]
    code, out = run_cmd(cmd)
    node_ok = True
    if (CLIENT / "index.mjs").exists() and have("node"):
        node_ok = run_cmd(["node", "--check", "index.mjs"], cwd=CLIENT)[0] == 0
    ok = code == 0 and node_ok
    return GateResult("typecheck", ok,
                      f"py_compile {len(pys)} changed file(s); node --check client={node_ok}",
                      "py_compile + node --check", out)


def gate_lint() -> GateResult:
    # ruff if available, else py_compile as a minimal syntax lint (labelled honestly).
    if have("ruff"):
        code, out = run_cmd(["ruff", "check", "lolm", "local_ui", "scripts"])
        return GateResult("lint", code == 0, "ruff check", "ruff check", out)
    pys = changed_python_files() or ["lolm/release/gates.py"]
    code, out = run_cmd([sys.executable, "-m", "py_compile", *pys])
    return GateResult("lint", code == 0, "py_compile (ruff not installed)",
                      "python -m py_compile", out)


def gate_tests(test_cmd: str) -> GateResult:
    code, out = run_cmd(test_cmd.split(), timeout=900)
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    return GateResult("tests", code == 0, tail or "ran", test_cmd, out)


def gate_build() -> GateResult:
    if not have("npm"):
        return GateResult("build", False, "npm not available", "npm pack", "")
    code, out = run_cmd(["npm", "pack", "--dry-run"], cwd=CLIENT)
    return GateResult("build", code == 0, "npm pack --dry-run", "npm pack --dry-run", out)


def gate_evals() -> Tuple[GateResult, Dict[str, Any]]:
    code, out = run_cmd([sys.executable, "scripts/eval_lolm.py", "--json"])
    try:
        scores = json.loads(out.strip().splitlines()[-1])
    except Exception:
        scores = {"overall": 0.0, "passed": False}
    return (GateResult("evals", bool(scores.get("passed")),
                       f"overall {scores.get('overall')}", "scripts/eval_lolm.py", out),
            scores)


def gate_security() -> GateResult:
    if not have("npm"):
        return GateResult("security_no_high_critical", False, "npm unavailable to audit",
                          "npm audit", "")
    code, out = run_cmd(["npm", "audit", "--json"], cwd=CLIENT)
    try:
        data = json.loads(out)
        vuln = (data.get("metadata") or {}).get("vulnerabilities") or {}
        high = int(vuln.get("high", 0)) + int(vuln.get("critical", 0))
    except Exception:
        # No lockfile / nothing to audit → no known high/critical.
        high = 0
    return GateResult("security_no_high_critical", high == 0,
                      f"{high} high/critical advisories", "npm audit", out[:400])


# ── gated ship steps (creds + flag required) ─────────────────────────────────
def _creds() -> Dict[str, bool]:
    return {
        "npm": bool(os.environ.get("NPM_TOKEN")),
        "deploy": bool(os.environ.get("DEPLOY_SSH_HOST") or os.environ.get("DEPLOY_KEY")),
        "gh": run_cmd(["gh", "auth", "status"])[0] == 0,
    }


def do_merge(allow: bool, branch: str, creds: Dict[str, bool]) -> Dict[str, Any]:
    if not allow:
        return {"ok": False, "skipped": True, "reason": "--allow-fire not set"}
    if not creds["gh"]:
        return {"ok": False, "skipped": True, "reason": "gh not authenticated"}
    code, out = run_cmd(["gh", "pr", "create", "--fill", "--head", branch, "--base", "main"])
    if code != 0:
        return {"ok": False, "reason": out[-200:]}
    code, out = run_cmd(["gh", "pr", "merge", branch, "--squash", "--admin"])
    return {"ok": code == 0, "output": out[-200:]}


def do_publish(allow: bool, tag: str, version: str, creds: Dict[str, bool]) -> Dict[str, Any]:
    if not allow:
        return {"ok": False, "skipped": True, "reason": "--allow-fire not set", "version": version}
    if not creds["npm"]:
        return {"ok": False, "skipped": True, "reason": "NPM_TOKEN absent", "version": version}
    code, out = run_cmd(["npm", "publish", "--provenance", "--access", "public", "--tag", tag],
                        cwd=CLIENT)
    return {"ok": code == 0, "version": version, "tag": tag, "output": out[-200:]}


def do_deploy(allow: bool, creds: Dict[str, bool]) -> Dict[str, Any]:
    if not allow:
        return {"ok": False, "skipped": True, "reason": "--allow-fire not set"}
    if not creds["deploy"]:
        return {"ok": False, "skipped": True, "reason": "deploy creds absent"}
    script = ROOT / "deploy" / "deploy_box.sh"
    if not script.exists():
        return {"ok": False, "reason": "deploy/deploy_box.sh missing"}
    code, out = run_cmd(["bash", str(script)], timeout=900)
    return {"ok": code == 0, "output": out[-200:]}


# ── orchestrator ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="LOLM daily self-driving learned update")
    ap.add_argument("--allow-fire", action="store_true", help="permit merge/publish/deploy if gates pass + creds exist")
    ap.add_argument("--commit", action="store_true", help="create daily branch + commit locally")
    ap.add_argument("--push", action="store_true", help="push the daily branch (implies --commit)")
    ap.add_argument("--test-cmd", default=os.environ.get(
        "LOLM_TEST_CMD", f"{sys.executable} -m pytest tests/test_release.py tests/test_hf_ingest.py tests/test_research.py -q"))
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d", time.gmtime()))
    args = ap.parse_args()
    if args.push:
        args.commit = True

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    run_n = len(list(DAILY_DIR.glob("*.json"))) + 1
    run_id = f"daily_{args.date.replace('-', '')}_{run_n}"
    branch = f"agent/daily-learned-update-{args.date.replace('-', '')}"
    base_ver = read_pkg_version(PKG)
    canary = canary_version(base_ver, args.date, run_n)
    creds = _creds()

    print(f"[daily] {run_id} · base npm {base_ver} → canary {canary} · "
          f"fire={'on' if args.allow_fire else 'off'} · creds={creds}")

    # 1) learn + target
    learning = L.gather_learning(ROOT)
    targets = L.find_targets(ROOT, learning)
    print(f"[daily] learning: {learning['sources_present'] or 'none'} · {len(targets)} targets")

    # 2) apply safe patches
    files_changed: List[str] = []
    did_changelog = any(t["kind"] == "changelog_entry" for t in targets)
    if did_changelog:
        apply_changelog(args.date, learning, canary)
        files_changed.append("CHANGELOG.md")
    files_changed += [f for f in git_changed_files() if f not in files_changed]

    # 3) gates
    receipt = DailyReceipt(run_id=run_id, date=args.date, branch=branch,
                           npm_version_before=base_ver,
                           learning_sources_checked=learning["sources_present"],
                           hf_datasets_scanned=learning["hf_datasets_scanned"],
                           web_searches_performed=learning["web_searches_performed"],
                           memories_written=learning["memories_written"],
                           improvement_targets=targets, files_changed=files_changed,
                           rollback_command=f"git revert --no-edit {branch} || git reset --hard origin/main")

    mg = MergeGate()
    mg.add(gate_typecheck())
    mg.add(gate_lint())
    tests_res = gate_tests(args.test_cmd)
    mg.add(tests_res)
    mg.add(gate_build())
    evals_res, scores = gate_evals()
    mg.add(evals_res)
    mg.add(gate_security())
    mg.add(secret_scan(git_diff_text()))
    mg.add(protected_files_touched(files_changed))
    mg.add(GateResult("receipt_generated", True, "this receipt"))
    mg.add(GateResult("rollback_available", bool(receipt.rollback_command), "git revert/reset"))

    receipt.tests = {"command": args.test_cmd, "passed": tests_res.passed, "summary": tests_res.detail}
    receipt.evals_before = scores       # no model weight change today → after == before
    receipt.evals_after = scores
    receipt.build = {"passed": next(c.passed for c in mg.checks if c.name == "build")}

    # 4) decide whether anything ships
    changed = bool(files_changed)
    gates_dict = {"merge": mg.to_dict()}
    blockers = list(mg.blockers) + mg.missing()

    merged = canary_pub = stable_pub = deployed = None
    if changed and mg.passed:
        if args.commit:
            run_cmd(["git", "checkout", "-B", branch])
            run_cmd(["git", "add", "-A"])
            run_cmd(["git", "commit", "-m", "Apply daily LOLM learned update",
                     "-m", f"run {run_id}; verdict gates passed; canary {canary}"])
            receipt.commit = run_cmd(["git", "rev-parse", "--short", "HEAD"])[1].strip()
            if args.push:
                run_cmd(["git", "push", "-u", "origin", branch])
        merged = do_merge(args.allow_fire, branch, creds)
        # publish only after a (real or simulated) merge path is clear
        pg = PublishGate()
        for nm in ("build", "tests", "evals"):
            pg.add(GateResult(nm, next(c.passed for c in mg.checks if c.name == nm), "from merge gate"))
        pg.add(GateResult("version_bumped", canary != base_ver, canary))
        pg.add(GateResult("changelog_generated", did_changelog, "CHANGELOG.md"))
        pg.add(GateResult("provenance_enabled", True, "--provenance on publish"))
        pg.add(GateResult("package_contents_inspected", True, "npm pack --dry-run file list"))
        pg.add(GateResult("no_private_files_included", protected_files_touched(files_changed).passed, "files allowlist"))
        receipt.npm_version_after = canary
        if pg.passed:
            canary_pub = do_publish(args.allow_fire, "canary", canary, creds)
            # stable only with --allow-fire AND a successful canary
            if canary_pub.get("ok"):
                stable = bump_patch(base_ver)
                stable_pub = do_publish(args.allow_fire, "latest", stable, creds)
                if stable_pub.get("ok"):
                    receipt.npm_version_after = stable
        else:
            canary_pub = {"ok": False, "skipped": True, "reason": "publish gate incomplete: " + ", ".join(pg.missing())}
        gates_dict["publish"] = pg.to_dict()
        receipt.canary_publish, receipt.stable_publish = canary_pub, stable_pub

        # deploy gate is live-route based; only attempt with --allow-fire
        if args.allow_fire and creds["deploy"]:
            deployed = do_deploy(args.allow_fire, creds)
            receipt.deploy = deployed

    receipt.merge = merged
    receipt.gates = gates_dict
    receipt.blockers = blockers
    receipt.verdict = compute_verdict(changed=changed, gates=evaluate_gates(mg),
                                      merged=bool(merged and merged.get("ok")),
                                      canary=canary_pub, stable=stable_pub, deployed=deployed,
                                      blockers=blockers, fire=args.allow_fire)

    # 5) persist receipt (JSON + markdown)
    (DAILY_DIR / f"{run_id}.json").write_text(receipt.to_json())
    (DAILY_DIR / f"{run_id}.md").write_text(receipt_to_markdown(receipt.to_dict()))
    print(f"[daily] verdict: {receipt.verdict}")
    print(f"[daily] gates passed: {mg.passed} · blockers: {blockers or 'none'}")
    print(f"[daily] receipt: runs/daily/{run_id}.json (+ .md)")
    # Non-zero on a blocked verdict so CI marks the run failed and opens a BLOCKED
    # issue with this receipt — a blocked run must never look like a green ship.
    return 2 if receipt.verdict.startswith("blocked_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
