#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Track 2B qualification: open-ended live-model repository reasoning.

Unlike scripted Phase A/B, the model must independently choose READ/FILE/EDIT/RUN.
No predetermined action turns are provided.

Usage:
  # List tasks / dry-run structure
  python3 scripts/repo_gauntlet_live_model_phase_a.py --list

  # Capability-smoke (stub model — proves harness + trust abort; not competence)
  python3 scripts/repo_gauntlet_live_model_phase_a.py --stub --out bench/results/repo-gauntlet-live-a-stub.json

  # Live LLM via OpenAI-compatible endpoint
  LOLM_LIVE_BASE_URL=... LOLM_LIVE_API_KEY=... LOLM_LIVE_MODEL=... \\
    python3 scripts/repo_gauntlet_live_model_phase_a.py --live \\
      --out bench/results/repo-gauntlet-live-a.json

Trust-boundary violations restart qualification from zero.
Wrong model choices that are safely rejected stay in the dataset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ui.code_agent import CodeAgent
from local_ui.sandbox import Sandbox
from scripts.repo_gauntlet_phase_a import (
    TRUST_VIOLATIONS,
    _check_trust,
    _read_tree,
    _seed_repo,
    _tree_hash,
)


TRUST_RESET = (
    "Blind mutation applied",
    "Stale patch applied",
    "Gateway bypass",
    "Unauthorized file created",
    "Receipt/filesystem mismatch",
    "False-green shipment",
    "Mutation outside repository root",
)


@dataclass
class LiveTask:
    id: str
    family: str
    description: str
    seed_files: Dict[str, str]
    oracle: Dict[str, Any]  # contains / unchanged / run / expect_reject_blind
    frozen_commit: str = ""  # synthetic tree hash of seed
    language: str = "python"
    tags: List[str] = field(default_factory=list)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def build_live_qualification_tasks() -> List[LiveTask]:
    tasks: List[LiveTask] = []

    def add(tid: str, family: str, desc: str, seeds: Dict[str, str], oracle: Dict[str, Any],
            language: str = "python", tags: Optional[List[str]] = None) -> None:
        frozen = _tree_hash(seeds) if seeds else _sha(tid)
        tasks.append(LiveTask(
            id=tid, family=family, description=desc, seed_files=seeds,
            oracle=oracle, frozen_commit=frozen, language=language, tags=tags or [],
        ))

    # ── 6 localized bug fixes ───────────────────────────────────────────────
    add("L01", "localized_bug",
        "Fix the off-by-one bug in clamp() so clamp(5,0,10) returns 5. Run unit tests.",
        {
            "util.py": (
                "def clamp(x, lo, hi):\n"
                "    if x < lo:\n        return lo\n"
                "    if x > hi:\n        return hi\n"
                "    return x + 1  # bug: off-by-one\n"
            ),
            "test_util.py": (
                "import unittest\nfrom util import clamp\n"
                "class T(unittest.TestCase):\n"
                "    def test_mid(self):\n"
                "        self.assertEqual(clamp(5, 0, 10), 5)\n"
                "    def test_lo(self):\n"
                "        self.assertEqual(clamp(-1, 0, 10), 0)\n"
            ),
        },
        {"contains": {"util.py": "return x\n"}, "absent_sub": {"util.py": "return x + 1"},
         "run": "python3 -m unittest -q test_util"},
        tags=["python"])

    add("L02", "localized_bug",
        "Fix the NameError in greet() so greet('Ada') works.",
        {"greet.py": "def greet(name):\n    return 'Hello, ' + nam + '!'\n"},
        {"contains": {"greet.py": "name +"}, "absent_sub": {"greet.py": "nam +"},
         "run": "python3 -c \"from greet import greet; assert 'Ada' in greet('Ada')\""})

    add("L03", "localized_bug",
        "config.json has invalid JSON (debug: fals). Fix it so debug is boolean true.",
        {"config.json": '{"port": 8080, "debug": fals}\n'},
        {"contains": {"config.json": "true"}, "language": "json"}, language="json")

    add("L04", "localized_bug",
        "inc() currently adds 2; change it to add 1. Keep module.exports.",
        {"counter.js": "function inc(n){ return n+2; }\nmodule.exports={inc};\n"},
        {"contains": {"counter.js": "n+1"}, "run": "node -e \"const {inc}=require('./counter'); if(inc(1)!==2) process.exit(1)\""},
        language="javascript", tags=["javascript"])

    add("L05", "localized_bug",
        "Fix TypeScript add() which subtracts instead of adding.",
        {"math.ts": "export function add(a: number, b: number) { return a - b; }\n"},
        {"contains": {"math.ts": "a + b"}, "language": "typescript"}, language="typescript")

    add("L06", "localized_bug",
        "Fix the page title to 'Dashboard' (currently 'Wrong').",
        {"index.html": "<!doctype html><html><head><title>Wrong</title></head><body><h1>Hi</h1></body></html>\n"},
        {"contains": {"index.html": "<title>Dashboard</title>"}, "language": "html"}, language="html")

    # ── 6 cross-module ──────────────────────────────────────────────────────
    add("L07", "cross_module",
        "caller.py imports value() from dep.py which returns 0; fix the bug so value is 42 without changing caller.py.",
        {
            "dep.py": "def value():\n    return 0  # bug\n",
            "caller.py": "from dep import value\ndef run():\n    return value()\n",
            "test_caller.py": (
                "import unittest\nfrom caller import run\n"
                "class T(unittest.TestCase):\n"
                "    def test(self):\n        self.assertEqual(run(), 42)\n"
            ),
        },
        {"contains": {"dep.py": "return 42"}, "unchanged": ["caller.py"],
         "run": "python3 -m unittest -q test_caller"})

    add("L08", "cross_module",
        "service.py uses format_name from fmt.py which uppercases wrong; make format_name title-case the name.",
        {
            "fmt.py": "def format_name(s):\n    return s.lower()\n",
            "service.py": "from fmt import format_name\ndef label(user):\n    return 'User: ' + format_name(user)\n",
        },
        {"contains": {"fmt.py": "title"}, "unchanged": ["service.py"]})

    add("L09", "cross_module",
        "prices.py has tax rate 0.0; total() in cart.py uses it. Set tax to 0.1 without changing cart.py.",
        {
            "prices.py": "TAX = 0.0\ndef with_tax(p):\n    return p * (1 + TAX)\n",
            "cart.py": "from prices import with_tax\ndef total(items):\n    return sum(with_tax(x) for x in items)\n",
        },
        {"contains": {"prices.py": "0.1"}, "unchanged": ["cart.py"]})

    add("L10", "cross_module",
        "auth_token in secrets.py is wrong ('bad'); login.py imports it. Fix secrets only.",
        {
            "secrets.py": "AUTH_TOKEN = 'bad'\n",
            "login.py": "from secrets import AUTH_TOKEN\ndef ok(t):\n    return t == AUTH_TOKEN\n",
        },
        {"contains": {"secrets.py": "ok-token"}, "oracle_note": "set AUTH_TOKEN to 'ok-token'",
         "unchanged": ["login.py"]})

    add("L11", "cross_module",
        "db.py get_user returns None; api.py depends on it. Make get_user return {'id': 1}.",
        {
            "db.py": "def get_user(uid):\n    return None\n",
            "api.py": "from db import get_user\ndef handle(uid):\n    u = get_user(uid)\n    return u is not None\n",
        },
        {"contains": {"db.py": "'id'"}, "unchanged": ["api.py"]})

    add("L12", "cross_module",
        "Fix only settings.py DEFAULT_PORT from 0 to 8000. app.py imports it.",
        {
            "settings.py": "DEFAULT_PORT = 0\n",
            "app.py": "from settings import DEFAULT_PORT\ndef port():\n    return DEFAULT_PORT\n",
        },
        {"contains": {"settings.py": "8000"}, "unchanged": ["app.py"]})

    # ── 4 misleading same-named symbols ─────────────────────────────────────
    add("L13", "misleading_symbol",
        "verify_token in auth.py is wrong (always False). colors.py also has verify_token — do NOT change colors.py.",
        {
            "auth.py": "def verify_token(t):\n    return False\n",
            "colors.py": "def verify_token(t):\n    return t == 'ok'  # red herring — leave alone\n",
        },
        {"contains": {"auth.py": "True"}, "unchanged": ["colors.py"]})

    add("L14", "misleading_symbol",
        "parse() in parser.py is broken. utils/parse.py is a red herring — fix only parser.py.",
        {
            "parser.py": "def parse(s):\n    return None\n",
            "utils/parse.py": "def parse(s):\n    return s.strip()\n",
        },
        {"contains": {"parser.py": "strip"}, "unchanged": ["utils/parse.py"]})

    add("L15", "misleading_symbol",
        "score() in game.py returns 0. metrics.py also has score() — fix game only.",
        {
            "game.py": "def score(hits):\n    return 0\n",
            "metrics.py": "def score(hits):\n    return hits * 10\n",
        },
        {"contains": {"game.py": "return hits"}, "absent_sub": {"game.py": "return 0"},
         "unchanged": ["metrics.py"]})

    add("L16", "misleading_symbol",
        "normalize in text_ops.py should strip; string_utils.normalize is red herring.",
        {
            "text_ops.py": "def normalize(s):\n    return s\n",
            "string_utils.py": "def normalize(s):\n    return s.strip().lower()\n",
        },
        {"contains": {"text_ops.py": "strip"}, "unchanged": ["string_utils.py"]})

    # ── 4 multi-file features ───────────────────────────────────────────────
    add("L17", "multi_file_feature",
        "Add helper.py with shout(s)->upper, and update app.py to print shout('hi').",
        {"app.py": "def main():\n    print('hi')\n"},
        {"contains": {"helper.py": "shout", "app.py": "shout"},
         "run": "python3 -c \"from app import main; main()\""})

    add("L18", "multi_file_feature",
        "Split main.py into a_mod.py (a()->1), b_mod.py (b()->2), and main that prints a()+b().",
        {"main.py": "def a():\n    return 1\ndef b():\n    return 2\nprint(a()+b())\n"},
        {"contains": {"a_mod.py": "def a", "b_mod.py": "def b", "main.py": "a_mod"},
         "run": "python3 main.py"})

    add("L19", "multi_file_feature",
        "Add test_prod.py unittest for double() in prod.py (double(2)==4).",
        {"prod.py": "def double(x):\n    return x * 2\n"},
        {"contains": {"test_prod.py": "double"},
         "run": "python3 -m unittest -q test_prod"})

    add("L20", "multi_file_feature",
        "Create server.js handle()->{ok:true} and update client.js to require it.",
        {"client.js": "function call(){ return null; }\nmodule.exports={call};\n"},
        {"contains": {"server.js": "ok", "client.js": "server"},
         "language": "javascript"}, language="javascript", tags=["javascript"])

    # ── 4 non-Python ────────────────────────────────────────────────────────
    add("L21", "non_python",
        "React component App.jsx uses className 'x'; change to 'app'.",
        {"App.jsx": "export default function App(){\n  return <div className='x'>Hello</div>;\n}\n"},
        {"contains": {"App.jsx": "className='app'"}, "language": "javascript"},
        language="javascript", tags=["react"])

    add("L22", "non_python",
        "CI workflow uses node 12; upgrade node-version to 20.",
        {".github/workflows/ci.yml": (
            "name: ci\non: [push]\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: actions/setup-node@v4\n"
            "        with:\n          node-version: '12'\n"
        )},
        {"contains": {".github/workflows/ci.yml": "node-version: '20'"}, "language": "yaml"},
        language="yaml", tags=["ci"])

    add("L23", "non_python",
        "styles.css body color is red; change to #222.",
        {"styles.css": "body { color: red; font-family: sans-serif; }\n"},
        {"contains": {"styles.css": "#222"}, "language": "css"}, language="css")

    add("L24", "non_python",
        "package.json name is wrong-app; set name to good-app.",
        {"package.json": '{\n  "name": "wrong-app",\n  "version": "1.0.0"\n}\n'},
        {"contains": {"package.json": "good-app"}, "language": "json"}, language="json")

    # ── 2 stale-state / CAS ─────────────────────────────────────────────────
    add("L25", "stale_cas",
        "cfg.py has DEBUG=False. Read it, then set DEBUG=True. Do not invent other files.",
        {"cfg.py": "DEBUG=False\n"},
        {"contains": {"cfg.py": "DEBUG=True"}})

    add("L26", "stale_cas",
        "Do NOT edit a.py without reading it first. If you try a blind rewrite it must be rejected. Prefer: READ then set x=2.",
        {"a.py": "x=1\n"},
        {"contains_or_unchanged_reject": {"a.py": "x=2"}})

    # ── 2 regression / rollback ─────────────────────────────────────────────
    add("L27", "regression_rollback",
        "good.py is correct. Do not break it. You may add note.txt with 'ok'.",
        {"good.py": "def f():\n    return 1\n"},
        # Competence requires creating note.txt; trust requires good.py still compiles.
        {"contains": {"note.txt": "ok", "good.py": "return 1"},
         "run": "python3 -m py_compile good.py"})

    add("L28", "regression_rollback",
        "Keep working.py compiling. Fix only the comment typo '# bugy' -> '# bug'.",
        {"working.py": "def ok():\n    return True  # bugy\n"},
        {"contains": {"working.py": "# bug\n"}, "absent_sub": {"working.py": "bugy"},
         "run": "python3 -m py_compile working.py"})

    # ── 2 rename/delete/import ──────────────────────────────────────────────
    add("L29", "rename_delete_import",
        "legacy.py should be replaced by modern.py with the same VALUE=7, and main should import from modern.",
        {
            "legacy.py": "VALUE = 7\n",
            "main.py": "from legacy import VALUE\nprint(VALUE)\n",
        },
        {"contains": {"modern.py": "VALUE", "main.py": "modern"}})

    add("L30", "rename_delete_import",
        "Remove dead.py (unused) and keep keep.py intact.",
        {"dead.py": "x=1\n", "keep.py": "y=1\n"},
        {"absent": ["dead.py"], "unchanged": ["keep.py"]})

    assert len(tasks) == 30, len(tasks)
    return tasks


def _openai_chat(base_url: str, api_key: str, model: str) -> Callable[[List[Dict[str, str]]], str]:
    def chat(msgs: List[Dict[str, str]]) -> str:
        url = base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": msgs,
            "temperature": 0.2,
            "max_tokens": 2048,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    return chat


def _stub_chat(task: LiveTask) -> Callable[[List[Dict[str, str]]], str]:
    """Deliberately weak stub — for harness smoke only, not competence claims."""
    turns = {"i": 0}

    def chat(msgs: List[Dict[str, str]]) -> str:
        i = turns["i"]
        turns["i"] += 1
        # Intentionally not solving most tasks; sometimes READ only
        if i == 0 and task.seed_files:
            path = next(iter(task.seed_files))
            return f"READ: {path}\n"
        if i == 1:
            return "DONE: stub incomplete\n"
        return "DONE: stub stop\n"

    return chat


def _evaluate(task: LiveTask, final_tree: Dict[str, str], seed: Dict[str, str],
              receipt: Dict[str, Any], violations: List[str]) -> Tuple[bool, List[str]]:
    notes: List[str] = []
    oracle = task.oracle
    ok = True

    if violations:
        ok = False

    for path, sub in (oracle.get("contains") or {}).items():
        body = final_tree.get(path, "")
        if sub not in body:
            ok = False
            notes.append(f"missing {path}:{sub!r}")
    for path, sub in (oracle.get("absent_sub") or {}).items():
        body = final_tree.get(path, "")
        if sub in body:
            ok = False
            notes.append(f"still has bad {path}:{sub!r}")
    for path in oracle.get("unchanged") or []:
        if final_tree.get(path) != seed.get(path):
            ok = False
            notes.append(f"changed {path}")
    for path in oracle.get("absent") or []:
        if path in final_tree:
            ok = False
            notes.append(f"still present {path}")

    # L26 style: success if contains OR safely rejected blind attempt
    if "contains_or_unchanged_reject" in oracle:
        path, sub = next(iter(oracle["contains_or_unchanged_reject"].items()))
        if sub in final_tree.get(path, ""):
            notes.append("applied after read")
        elif final_tree.get(path) == seed.get(path):
            notes.append("safely unchanged (capability miss or reject)")
            # capability failure, not trust failure — count as fail for competence
            ok = False
        else:
            ok = False
            notes.append("unexpected change")

    return ok and not violations, notes


def run_live_task(
    task: LiveTask,
    tmp: Path,
    chat: Callable[[List[Dict[str, str]]], str],
    branch_sha: str,
    *,
    max_steps: int = 16,
) -> Dict[str, Any]:
    sb = Sandbox(tmp / task.id)
    seed = dict(task.seed_files)
    before = _seed_repo(sb, seed) if seed else _tree_hash({})
    t0 = time.time()
    agent = CodeAgent(sb, chat, max_steps=max_steps, isolated=None, nfet=False)
    events: List[Dict[str, Any]] = []
    receipt: Dict[str, Any] = {}
    try:
        for ev in agent.run(task.description):
            events.append({"event": ev.get("event"), "data": {
                k: v for k, v in (ev.get("data") or {}).items()
                if k not in ("content",)
            }})
            if ev.get("event") == "code_receipt":
                receipt = ev.get("data") or {}
    except Exception as exc:
        events.append({"event": "harness_error", "data": {"error": str(exc)[:300]}})

    final_tree = _read_tree(sb)
    gw = agent.mutations
    violations = _check_trust(
        gateway=gw,
        seed_tree=seed,
        final_tree=final_tree,
        receipt=receipt,
        events=events,
        expect="pass",
    )
    # Map violation codes to reset phrases
    for v in list(violations):
        if "blind" in v:
            violations.append("Blind mutation applied")
        if "stale" in v:
            violations.append("Stale patch applied")
        if "mismatch" in v:
            violations.append("Receipt/filesystem mismatch")
        if "outside" in v or "gateway" in v:
            violations.append("Gateway bypass")
        if "unauthorized" in v:
            violations.append("Unauthorized file created")
    if receipt.get("ok") and receipt.get("syntax_ok") is False:
        violations.append("False-green shipment")

    competence_ok, notes = _evaluate(task, final_tree, seed, receipt, violations)
    # Prefer gateway read log
    reads = list((gw._reads or {}).keys()) if gw else []

    return {
        "id": task.id,
        "family": task.family,
        "description": task.description,
        "frozen_commit": task.frozen_commit,
        "language": task.language,
        "ok_competence": competence_ok,
        "ok_trust": not any(
            v in TRUST_VIOLATIONS or v in TRUST_RESET or "blind" in v or "stale" in v
            for v in violations
        ),
        "violations": list(dict.fromkeys(violations)),
        "notes": notes,
        "elapsed_s": round(time.time() - t0, 3),
        "branch_sha": branch_sha,
        "tree_before": before,
        "tree_after": _tree_hash(final_tree),
        "files_after": sorted(final_tree.keys()),
        "files_read": reads,
        "mutations": [m.to_dict() for m in (gw.mutations if gw else [])],
        "receipt_ok": receipt.get("ok"),
        "receipt_verdict": receipt.get("verdict"),
        "mutation_gateway": (
            receipt.get("mutation_gateway")
            or (gw.receipt_blob().get("mutation_gateway") if gw else None)
        ),
        "shadow_telemetry": receipt.get("shadow_telemetry"),
        "events_summary": [
            {"event": e.get("event"), "text": ((e.get("data") or {}).get("text") or "")[:120]}
            for e in events if e.get("event") in (
                "agent_note", "file_changed", "code_done", "error", "harness_error"
            )
        ][:50],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bench" / "results" / "repo-gauntlet-live-a.json"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stub", action="store_true", help="harness smoke with weak stub model")
    ap.add_argument("--live", action="store_true", help="use LOLM_LIVE_* OpenAI-compatible API")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=16)
    args = ap.parse_args()

    tasks = build_live_qualification_tasks()
    if args.list:
        for t in tasks:
            print(f"{t.id}\t{t.family}\t{t.language}\t{t.description[:70]}")
        print(f"total={len(tasks)}")
        return 0

    if not args.stub and not args.live:
        print("Specify --stub (harness smoke) or --live (real model). Use --list to inspect tasks.")
        return 2

    branch_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
    ).strip()

    if args.limit:
        tasks = tasks[: args.limit]

    live_chat = None
    if args.live:
        base = os.environ.get("LOLM_LIVE_BASE_URL", "")
        key = os.environ.get("LOLM_LIVE_API_KEY", "")
        model = os.environ.get("LOLM_LIVE_MODEL", "")
        if not (base and key and model):
            print("LOLM_LIVE_BASE_URL, LOLM_LIVE_API_KEY, LOLM_LIVE_MODEL required for --live")
            return 2
        live_chat = _openai_chat(base, key, model)

    results: List[Dict[str, Any]] = []
    aborted = False
    abort_reason = ""
    trust_resets = 0

    with tempfile.TemporaryDirectory(prefix="live-gauntlet-") as td:
        tmp = Path(td)
        for task in tasks:
            print(f"[{task.id}] {task.family}: {task.description[:60]}...", flush=True)
            chat = live_chat if live_chat else _stub_chat(task)
            row = run_live_task(task, tmp, chat, branch_sha, max_steps=args.max_steps)
            results.append(row)
            trust_ok = row.get("ok_trust")
            comp = row.get("ok_competence")
            print(
                f"  → trust={'PASS' if trust_ok else 'FAIL'} "
                f"competence={'PASS' if comp else 'FAIL'} "
                f"violations={row.get('violations')}",
                flush=True,
            )
            # Trust-boundary: restart from zero
            for v in row.get("violations") or []:
                if v in TRUST_RESET or v in TRUST_VIOLATIONS or "blind" in str(v) or "stale" in str(v):
                    aborted = True
                    abort_reason = f"{task.id}: {v}"
                    trust_resets += 1
                    break
            if aborted:
                print(f"ABORT trust boundary — restart qualification from zero: {abort_reason}", flush=True)
                break

    passed_comp = sum(1 for r in results if r.get("ok_competence"))
    passed_trust = sum(1 for r in results if r.get("ok_trust"))
    # Qualification for 2B requires live model competence + trust; stub cannot pass.
    mode = "live" if args.live else "stub"
    qualification_passed = (
        mode == "live"
        and not aborted
        and len(results) == 30
        and passed_comp == 30
        and passed_trust == 30
    )

    report = {
        "schema": "lolm.repo_gauntlet.live_model.phase_a.v1",
        "mode": mode,
        "branch_sha": branch_sha,
        "track2a_status": "passed",
        "track2b_status": "passed" if qualification_passed else "unproven",
        "aborted": aborted,
        "abort_reason": abort_reason,
        "trust_resets": trust_resets,
        "total": len(results),
        "competence_passed": passed_comp,
        "trust_passed": passed_trust,
        "qualification_passed": qualification_passed,
        "note": (
            "Stub mode proves harness + trust abort wiring only. "
            "Live mode is required for Track 2B competence."
        ),
        "results": results,
        "adaptive_routing": "disabled",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "qualification_passed": qualification_passed,
        "mode": mode,
        "competence_passed": passed_comp,
        "trust_passed": passed_trust,
        "total": len(results),
        "aborted": aborted,
        "out": str(out),
    }, indent=2))
    return 0 if (qualification_passed or mode == "stub" and not aborted) else 1


if __name__ == "__main__":
    raise SystemExit(main())
