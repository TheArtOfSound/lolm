#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Phase A: 20-task organic repository qualification for Track 2.

Uses real CodeAgent + MutationGateway + Sandbox. Scripted model turns exercise
mutation policy; trust-boundary violations abort the whole set.

Usage:
  python3 scripts/repo_gauntlet_phase_a.py
  python3 scripts/repo_gauntlet_phase_a.py --out bench/results/repo-gauntlet-phase-a.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ui.code_agent import CodeAgent
from local_ui.sandbox import Sandbox
from lolm.mutation_gateway import MutationGateway, MutationState
from lolm.repo_context import content_hash


# ── Trust boundary ────────────────────────────────────────────────────────────

TRUST_VIOLATIONS = (
    "blind_existing_file_mutation",
    "stale_patch_applied",
    "mutation_outside_gateway",
    "unrecorded_automatic_repair",
    "receipt_filesystem_mismatch",
    "regression_accepted_as_green",
)


@dataclass
class TaskSpec:
    id: str
    family: str
    description: str
    seed_files: Dict[str, str]
    script: List[str]  # model turns in FILE/EDIT/RUN protocol
    expect: str  # pass | reject_blind | reject_stale | reject_create | rollback | multi
    oracle: str = ""  # post-condition description


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _tree_hash(files: Dict[str, str]) -> str:
    payload = json.dumps({k: _sha(v) for k, v in sorted(files.items())}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _seed_repo(sb: Sandbox, files: Dict[str, str]) -> str:
    for path, content in files.items():
        sb.write_file(path, content, reason="gauntlet_seed")
    return _tree_hash(files)


def _read_tree(sb: Sandbox) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in sb.list_files(limit=200):
        try:
            body = sb.read_file(path)
            if body is not None:
                out[path] = body if isinstance(body, str) else body.decode("utf-8", "replace")
        except Exception:
            pass
    return out


def _scripted_chat(turns: List[str]) -> Callable[[List[Dict[str, str]]], str]:
    box = {"i": 0, "turns": list(turns)}

    def chat(msgs: List[Dict[str, str]]) -> str:
        if box["i"] >= len(box["turns"]):
            # Exhausted script: stop cleanly
            return "DONE: budget exhausted in script"
        t = box["turns"][box["i"]]
        box["i"] += 1
        return t

    return chat


def _check_trust(
    *,
    gateway: Optional[MutationGateway],
    seed_tree: Dict[str, str],
    final_tree: Dict[str, str],
    receipt: Dict[str, Any],
    events: List[Dict[str, Any]],
    expect: str,
) -> List[str]:
    """Return list of trust-boundary violation codes (empty = clean)."""
    violations: List[str] = []

    # Gateway integrity
    if gateway is not None:
        if not gateway.assert_no_blind_existing_edits():
            violations.append("blind_existing_file_mutation")
        for m in gateway.mutations:
            if m.state in (MutationState.APPLIED.value, MutationState.ACCEPTED.value):
                if m.operation in ("edit", "full_rewrite", "range_edit", "symbol_edit", "delete"):
                    if not m.read_before_edit:
                        violations.append("blind_existing_file_mutation")
                    if m.rejection_reason == "" and not m.compare_and_swap_passed and m.operation != "create":
                        # applied without CAS is fatal
                        if m.state == MutationState.APPLIED.value and m.pre_apply_sha256:
                            if m.read_sha256 and m.pre_apply_sha256 != m.read_sha256:
                                violations.append("stale_patch_applied")

        # Receipt / filesystem match for applied mutations
        mg = (receipt.get("mutation_gateway") or {})
        for m in mg.get("mutations") or []:
            if m.get("state") not in ("applied", "accepted"):
                continue
            path = m.get("path") or ""
            post = m.get("post_apply_sha256") or ""
            if m.get("operation") == "delete":
                if path in final_tree:
                    violations.append("receipt_filesystem_mismatch")
            elif m.get("operation") == "create" or m.get("operation") in (
                "edit", "full_rewrite", "range_edit", "symbol_edit"
            ):
                body = final_tree.get(path)
                if body is None and m.get("operation") != "rename":
                    # rename moves path
                    continue
                if body is not None and post and _sha(body) != post:
                    violations.append("receipt_filesystem_mismatch")
            if m.get("state") in ("applied", "accepted") and m.get("rejection_reason") == "stale_revision":
                violations.append("stale_patch_applied")

    # Direct write outside gateway: look for unguarded write notes
    for e in events:
        if e.get("event") != "agent_note":
            continue
        text = (e.get("data") or {}).get("text") or ""
        if "unguarded" in text.lower():
            violations.append("mutation_outside_gateway")

    # Regression accepted as green: receipt ok but syntax broken
    if receipt.get("ok") and receipt.get("syntax_ok") is False:
        violations.append("regression_accepted_as_green")

    return list(dict.fromkeys(violations))


# ── Task definitions ──────────────────────────────────────────────────────────

def build_phase_a_tasks() -> List[TaskSpec]:
    tasks: List[TaskSpec] = []

    # ── 6 existing-file bug fixes ──
    tasks.append(TaskSpec(
        id="A01", family="existing_bugfix",
        description="Fix off-by-one in clamp()",
        seed_files={
            "util.py": "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x + 1  # bug\n",
            "test_util.py": (
                "import unittest\nfrom util import clamp\n"
                "class T(unittest.TestCase):\n"
                "    def test_mid(self):\n"
                "        self.assertEqual(clamp(5, 0, 10), 5)\n"
            ),
        },
        script=[
            "READ: util.py\n",
            "FILE: util.py\n```\n"
            "def clamp(x, lo, hi):\n"
            "    if x < lo:\n"
            "        return lo\n"
            "    if x > hi:\n"
            "        return hi\n"
            "    return x\n"
            "```\n"
            "RUN: python3 -m unittest -q test_util\n",
            "DONE: fixed clamp\n",
        ],
        expect="pass",
        oracle="clamp(5,0,10)==5",
    ))
    tasks.append(TaskSpec(
        id="A02", family="existing_bugfix",
        description="Fix name error in greet()",
        seed_files={
            "greet.py": "def greet(name):\n    return 'Hello, ' + nam + '!'\n",
        },
        script=[
            "READ: greet.py\n",
            "FILE: greet.py\n```\ndef greet(name):\n    return 'Hello, ' + name + '!'\n```\n"
            "RUN: python3 -c \"from greet import greet; print(greet('Ada'))\"\n",
            "DONE: fixed name\n",
        ],
        expect="pass",
    ))
    tasks.append(TaskSpec(
        id="A03", family="existing_bugfix",
        description="JS fix double count",
        seed_files={
            "counter.js": "function inc(n){ return n+2; }\nmodule.exports={inc};\n",
        },
        script=[
            "READ: counter.js\n",
            "FILE: counter.js\n```\nfunction inc(n){ return n+1; }\nmodule.exports={inc};\n```\n"
            "RUN: node -e \"const {inc}=require('./counter'); if(inc(1)!==2) process.exit(1); console.log('ok')\"\n",
            "DONE: fixed inc\n",
        ],
        expect="pass",
    ))
    tasks.append(TaskSpec(
        id="A04", family="existing_bugfix",
        description="Config typo fix",
        seed_files={
            "config.json": '{"port": 8000, "debug": "ture"}\n',
        },
        script=[
            "READ: config.json\n",
            "FILE: config.json\n```\n{\"port\": 8000, \"debug\": true}\n```\n"
            "RUN: python3 -c \"import json; print(json.load(open('config.json'))['debug'])\"\n",
            "DONE: fixed config\n",
        ],
        expect="pass",
    ))
    tasks.append(TaskSpec(
        id="A05", family="existing_bugfix",
        description="HTML title fix",
        seed_files={
            "index.html": "<!doctype html><html><head><title>Wrong</title></head>"
                         "<body><h1>App</h1><script>console.log(1)</script></body></html>\n",
        },
        script=[
            "READ: index.html\n",
            "FILE: index.html\n```\n<!doctype html><html><head><title>App</title></head>"
            "<body><h1>App</h1><script>console.log(1)</script></body></html>\n```\n"
            "DONE: fixed title\n",
        ],
        expect="pass",
    ))
    tasks.append(TaskSpec(
        id="A06", family="existing_bugfix",
        description="TS export fix",
        seed_files={
            "math.ts": "export function add(a: number, b: number) { return a - b; }\n",
        },
        script=[
            "READ: math.ts\n",
            "FILE: math.ts\n```\nexport function add(a: number, b: number) { return a + b; }\n```\n"
            "DONE: fixed add\n",
        ],
        expect="pass",
    ))

    # ── 4 multi-file ──
    tasks.append(TaskSpec(
        id="A07", family="multi_file",
        description="Add helper and wire import",
        seed_files={
            "app.py": "def main():\n    print('hi')\n",
        },
        script=[
            "READ: app.py\n",
            "FILE: helper.py\n```\ndef shout(s):\n    return s.upper()\n```\n",
            "FILE: app.py\n```\nfrom helper import shout\ndef main():\n    print(shout('hi'))\n```\n"
            "RUN: python3 -c \"from app import main; main()\"\n",
            "DONE: multi-file\n",
        ],
        expect="multi",
    ))
    tasks.append(TaskSpec(
        id="A08", family="multi_file",
        description="Split utils into two modules",
        seed_files={
            "utils.py": "def a():\n    return 1\ndef b():\n    return 2\n",
            "main.py": "from utils import a, b\nprint(a()+b())\n",
        },
        script=[
            "READ: utils.py\n",
            "READ: main.py\n",
            "FILE: a_mod.py\n```\ndef a():\n    return 1\n```\n",
            "FILE: b_mod.py\n```\ndef b():\n    return 2\n```\n",
            "FILE: main.py\n```\nfrom a_mod import a\nfrom b_mod import b\nprint(a()+b())\n```\n"
            "RUN: python3 main.py\n",
            "DONE: split\n",
        ],
        expect="multi",
    ))
    tasks.append(TaskSpec(
        id="A09", family="multi_file",
        description="JS client+server pair",
        seed_files={
            "server.js": "function handle(){ return {ok:false}; }\nmodule.exports={handle};\n",
            "client.js": "const {handle}=require('./server');\nconsole.log(handle());\n",
        },
        script=[
            "READ: server.js\n",
            "FILE: server.js\n```\nfunction handle(){ return {ok:true}; }\nmodule.exports={handle};\n```\n"
            "RUN: node client.js\n",
            "DONE: fixed pair\n",
        ],
        expect="multi",
    ))
    tasks.append(TaskSpec(
        id="A10", family="multi_file",
        description="Add test for product function",
        seed_files={
            "prod.py": "def double(x):\n    return x * 2\n",
        },
        script=[
            "READ: prod.py\n",
            "FILE: test_prod.py\n```\nimport unittest\nfrom prod import double\n"
            "class T(unittest.TestCase):\n"
            "    def test_double(self):\n"
            "        self.assertEqual(double(3), 6)\n```\n"
            "RUN: python3 -m unittest -q test_prod\n",
            "DONE: tests added\n",
        ],
        expect="multi",
    ))

    # ── 3 misleading file selection ──
    tasks.append(TaskSpec(
        id="A11", family="misleading_selection",
        description="Same symbol name in wrong module — must edit auth.py not colors.py",
        seed_files={
            "auth.py": "def verify_token(t):\n    return False  # bug should be True for 'ok'\n",
            "colors.py": "def verify_token(t):\n    return 'red'\n",
        },
        script=[
            "READ: auth.py\n",
            "FILE: auth.py\n```\ndef verify_token(t):\n    return t == 'ok'\n```\n"
            "RUN: python3 -c \"from auth import verify_token; assert verify_token('ok')\"\n",
            "DONE: fixed auth\n",
        ],
        expect="pass",
        oracle="colors.py unchanged",
    ))
    tasks.append(TaskSpec(
        id="A12", family="misleading_selection",
        description="Stack-ish: fix dependency not caller",
        seed_files={
            "dep.py": "def value():\n    return 0  # should be 42\n",
            "caller.py": "from dep import value\ndef run():\n    return value()\n",
        },
        script=[
            "READ: dep.py\n",
            "FILE: dep.py\n```\ndef value():\n    return 42\n```\n"
            "RUN: python3 -c \"from caller import run; assert run()==42\"\n",
            "DONE: fixed dep\n",
        ],
        expect="pass",
    ))
    tasks.append(TaskSpec(
        id="A13", family="misleading_selection",
        description="Do not create duplicate util.py",
        seed_files={
            "pkg/util.py": "def f():\n    return 1\n",
            "main.py": "from pkg.util import f\nprint(f())\n",
        },
        script=[
            "READ: pkg/util.py\n",
            "FILE: util.py\n```\ndef f():\n    return 1\n```\n"
            "DONE: should fail authorization\n",
        ],
        expect="reject_create",
    ))

    # ── 3 stale / CAS ──
    tasks.append(TaskSpec(
        id="A14", family="stale_cas",
        description="Blind edit without READ must fail",
        seed_files={"a.py": "x=1\n"},
        script=[
            # No READ — full FILE rewrite of existing file
            "FILE: a.py\n```\nx=2\n```\nDONE: try blind\n",
        ],
        expect="reject_blind",
    ))
    tasks.append(TaskSpec(
        id="A15", family="stale_cas",
        description="Gateway rejects stale CAS directly",
        seed_files={"a.py": "v=1\n"},
        script=[],  # exercised in harness special-case
        expect="reject_stale",
    ))
    tasks.append(TaskSpec(
        id="A16", family="stale_cas",
        description="Read then successful CAS edit",
        seed_files={"cfg.py": "DEBUG=False\n"},
        script=[
            "READ: cfg.py\n",
            # Product EDIT protocol is <<< old === new >>> (not markdown fences).
            "EDIT: cfg.py\n"
            "<<<\n"
            "DEBUG=False\n"
            "===\n"
            "DEBUG=True\n"
            ">>>\n"
            "RUN: python3 -c \"import cfg; print(cfg.DEBUG)\"\n",
            "DONE: toggled\n",
        ],
        expect="pass",
    ))

    # ── 2 rollback ──
    tasks.append(TaskSpec(
        id="A17", family="rollback",
        description="Gateway rollback restores prior bytes",
        seed_files={"r.py": "ok=1\n"},
        script=[],  # harness special-case
        expect="rollback",
    ))
    tasks.append(TaskSpec(
        id="A18", family="rollback",
        description="Rollback create removes new file",
        seed_files={},
        script=[],
        expect="rollback",
    ))

    # ── 2 new-file authorization ──
    tasks.append(TaskSpec(
        id="A19", family="new_file_auth",
        description="HTML task rejects main.py create via gateway",
        seed_files={},
        script=[],
        expect="reject_create",
    ))
    tasks.append(TaskSpec(
        id="A20", family="new_file_auth",
        description="Authorized create of solution.py",
        seed_files={},
        script=[
            "FILE: solution.py\n```\ndef f():\n    return 42\nprint(f())\n```\n"
            "RUN: python3 solution.py\n",
            "DONE: created\n",
        ],
        expect="pass",
    ))

    return tasks


def _run_special(task: TaskSpec, tmp: Path) -> Dict[str, Any]:
    """Direct gateway exercises for CAS/rollback without model."""
    sb = Sandbox(tmp / task.id)
    seed = dict(task.seed_files)
    if seed:
        _seed_repo(sb, seed)
    gw = MutationGateway(
        sb,
        task=task.description,
        primary_language="html" if task.id == "A19" else "python",
        exact_count=1 if task.id == "A19" else None,
        required_paths=["index.html"] if task.id == "A19" else [],
    )
    violations: List[str] = []
    detail: Dict[str, Any] = {"special": True}

    try:
        if task.expect == "reject_stale":
            sb.write_file("a.py", "v=1\n", reason="seed")
            gw = MutationGateway(sb, task="stale")
            gw.read("a.py")
            prop = gw.authorize_edit("a.py", "v=2\n")
            r1 = gw.apply(prop)
            assert r1.compare_and_swap_passed
            r2 = gw.apply(prop)
            detail["second"] = r2.to_dict()
            if r2.state != MutationState.REJECTED.value:
                violations.append("stale_patch_applied")
            ok = r2.rejection_reason == "stale_revision"

        elif task.expect == "rollback" and task.id == "A17":
            sb.write_file("r.py", "ok=1\n", reason="seed")
            gw = MutationGateway(sb, task="rb")
            gw.read("r.py")
            rec = gw.write("r.py", "ok=2\n", creating=False)
            assert sb.read_file("r.py") == "ok=2\n"
            rb = gw.rollback(rec.mutation_id)
            detail["rollback"] = rb.to_dict() if rb else None
            ok = sb.read_file("r.py") == "ok=1\n" and bool(rb and rb.rollback)
            if not ok:
                violations.append("receipt_filesystem_mismatch")

        elif task.expect == "rollback" and task.id == "A18":
            gw = MutationGateway(sb, task="rb-create")
            rec = gw.write("new.py", "print(1)\n", creating=True)
            assert "new.py" in sb.list_files()
            rb = gw.rollback(rec.mutation_id)
            ok = "new.py" not in sb.list_files() and bool(rb and rb.rollback)
            if not ok:
                violations.append("receipt_filesystem_mismatch")

        elif task.expect == "reject_create" and task.id == "A19":
            gw = MutationGateway(sb, primary_language="html", task="snake")
            try:
                gw.authorize_create("main.py", "print(1)\n")
                ok = False
                violations.append("unauthorized create of main.py")
            except PermissionError as exc:
                detail["rejected"] = str(exc)
                ok = "HTML" in str(exc) or "Python" in str(exc)

        else:
            ok = False
            detail["error"] = "unknown special"

    except Exception as exc:
        ok = False
        detail["exception"] = str(exc)
        detail["trace"] = traceback.format_exc()[-500:]

    final = _read_tree(sb)
    return {
        "id": task.id,
        "family": task.family,
        "ok": ok,
        "expect": task.expect,
        "violations": violations,
        "detail": detail,
        "final_tree_hash": _tree_hash(final),
        "gateway": gw.receipt_blob() if gw else None,
    }


def run_codeagent_task(task: TaskSpec, tmp: Path, branch_sha: str) -> Dict[str, Any]:
    sb = Sandbox(tmp / task.id)
    seed = dict(task.seed_files)
    before_hash = _seed_repo(sb, seed) if seed else _tree_hash({})
    seed_tree = dict(seed)

    chat = _scripted_chat(task.script)
    agent = CodeAgent(sb, chat, max_steps=min(12, max(len(task.script) + 2, 4)),
                      isolated=None, nfet=False)
    events: List[Dict[str, Any]] = []
    receipt: Dict[str, Any] = {}
    t0 = time.time()
    try:
        for ev in agent.run(task.description):
            events.append({"event": ev.get("event"), "data": {
                k: v for k, v in (ev.get("data") or {}).items()
                if k not in ("content",)  # keep receipts lean
            }})
            if ev.get("event") == "code_receipt":
                receipt = ev.get("data") or {}
    except Exception as exc:
        events.append({"event": "harness_error", "data": {"error": str(exc)[:300]}})
    elapsed = time.time() - t0

    final_tree = _read_tree(sb)
    after_hash = _tree_hash(final_tree)
    gw = agent.mutations

    violations = _check_trust(
        gateway=gw,
        seed_tree=seed_tree,
        final_tree=final_tree,
        receipt=receipt,
        events=events,
        expect=task.expect,
    )

    # Family-specific oracle
    ok = False
    notes: List[str] = []
    if task.expect == "reject_blind":
        # Either mutation rejected notes or file unchanged
        unchanged = final_tree.get("a.py") == seed_tree.get("a.py")
        rejected = any(
            "rejected" in str((e.get("data") or {}).get("text") or "").lower()
            or "read-before-edit" in str((e.get("data") or {}).get("text") or "").lower()
            or "mutation rejected" in str((e.get("data") or {}).get("text") or "").lower()
            for e in events
        )
        ok = unchanged or rejected
        if not unchanged and not rejected:
            violations.append("blind_existing_file_mutation")
        notes.append(f"unchanged={unchanged} rejected_note={rejected}")

    elif task.expect == "reject_create":
        # A13: util.py at root should not appear if gateway blocks duplicate
        has_dup = "util.py" in final_tree and "pkg/util.py" in final_tree
        rejected = any("rejected" in str((e.get("data") or {}).get("text") or "").lower()
                       for e in events)
        ok = (not has_dup) or rejected
        if has_dup and not rejected:
            violations.append("unauthorized create")
        notes.append(f"has_dup={has_dup} rejected={rejected}")

    elif task.expect in ("pass", "multi"):
        # Prefer green receipt or expected content change without trust violations
        if task.id == "A01":
            ok = "return x" in final_tree.get("util.py", "") and "return x + 1" not in final_tree.get("util.py", "")
        elif task.id == "A02":
            ok = "name + " in final_tree.get("greet.py", "") or "name+" in final_tree.get("greet.py", "")
        elif task.id == "A03":
            ok = "n+1" in final_tree.get("counter.js", "").replace(" ", "")
        elif task.id == "A04":
            ok = "true" in final_tree.get("config.json", "").lower()
        elif task.id == "A05":
            ok = "<title>App</title>" in final_tree.get("index.html", "")
        elif task.id == "A06":
            ok = "a + b" in final_tree.get("math.ts", "")
        elif task.id == "A11":
            ok = ("t == 'ok'" in final_tree.get("auth.py", "") or 't == "ok"' in final_tree.get("auth.py", ""))
            if final_tree.get("colors.py") != seed_tree.get("colors.py"):
                notes.append("colors.py was modified (misleading selection risk)")
        elif task.id == "A12":
            ok = "return 42" in final_tree.get("dep.py", "")
        elif task.id == "A16":
            ok = "DEBUG=True" in final_tree.get("cfg.py", "")
        elif task.id == "A20":
            ok = "solution.py" in final_tree and "42" in final_tree.get("solution.py", "")
        elif task.id == "A07":
            ok = "helper.py" in final_tree and "shout" in final_tree.get("app.py", "")
        elif task.id == "A08":
            ok = "a_mod.py" in final_tree and "b_mod.py" in final_tree
        elif task.id == "A09":
            ok = "ok:true" in final_tree.get("server.js", "").replace(" ", "")
        elif task.id == "A10":
            ok = "test_prod.py" in final_tree
        else:
            ok = bool(receipt.get("ok")) or len(final_tree) >= len(seed_tree)
        if violations:
            ok = False

    return {
        "id": task.id,
        "family": task.family,
        "description": task.description,
        "expect": task.expect,
        "ok": ok and not violations,
        "violations": violations,
        "notes": notes,
        "elapsed_s": round(elapsed, 3),
        "branch_sha": branch_sha,
        "tree_before": before_hash,
        "tree_after": after_hash,
        "files_after": sorted(final_tree.keys()),
        # Full tree for Phase B declarative oracles (kept lean by size).
        "final_tree": {k: v for k, v in final_tree.items() if len(v) < 50_000},
        "seed_tree": seed_tree,
        "selection": (gw._selection_cache[:8] if gw else []),
        "mutations": [m.to_dict() for m in (gw.mutations if gw else [])],
        "receipt_verdict": receipt.get("verdict"),
        "receipt_ok": receipt.get("ok"),
        "receipt_sha": receipt.get("receipt_sha"),
        "mutation_gateway": (receipt.get("mutation_gateway") or (gw.receipt_blob().get("mutation_gateway") if gw else None)),
        "events_summary": [
            {"event": e.get("event"), "text": ((e.get("data") or {}).get("text") or "")[:120]}
            for e in events if e.get("event") in (
                "agent_note", "file_changed", "code_done", "error", "harness_error"
            )
        ][:40],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bench" / "results" / "repo-gauntlet-phase-a.json"))
    args = ap.parse_args()

    branch_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
    ).strip()
    tasks = build_phase_a_tasks()
    assert len(tasks) == 20, len(tasks)

    results: List[Dict[str, Any]] = []
    aborted = False
    abort_reason = ""

    with tempfile.TemporaryDirectory(prefix="repo-gauntlet-") as td:
        tmp = Path(td)
        for task in tasks:
            print(f"[{task.id}] {task.family}: {task.description} ...", flush=True)
            if task.script:
                row = run_codeagent_task(task, tmp, branch_sha)
            else:
                row = _run_special(task, tmp)
                row["branch_sha"] = branch_sha

            results.append(row)
            status = "PASS" if row.get("ok") else "FAIL"
            viol = row.get("violations") or []
            print(f"  → {status} violations={viol} notes={row.get('notes')}", flush=True)

            # Stop immediately on trust-boundary violation
            for v in viol:
                if v in TRUST_VIOLATIONS or v.startswith("blind") or v.startswith("stale"):
                    aborted = True
                    abort_reason = f"{task.id}: {v}"
                    break
            if aborted:
                print(f"ABORT trust boundary: {abort_reason}", flush=True)
                break

    passed = sum(1 for r in results if r.get("ok"))
    failed = len(results) - passed
    report = {
        "schema": "lolm.repo_gauntlet.phase_a.v1",
        "branch_sha": branch_sha,
        "aborted": aborted,
        "abort_reason": abort_reason,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "qualification_passed": (not aborted) and failed == 0 and len(results) == 20,
        "results": results,
        "helper_path_audit": {
            "active_repo_must_use_gateway": True,
            "known_bypass_surfaces": [
                "local_ui/agent_operator.py:write_file (operator loop — not CodeAgent)",
                "local_ui/sandbox_routes.py:write_file (HTTP sandbox API)",
                "local_ui/code_agent.py scratch Sandbox scoring (isolated candidates)",
                "lolm/reliability LGTS materialize (explicit restore path)",
                "resume_checkpoint writes (restore, not agent proposal)",
            ],
            "code_agent_product_path": "mutation_gateway required for FILE/EDIT/auto-strip/repair-race",
        },
        "metrics": {
            "blind_existing_file_mutations": sum(
                1 for r in results for v in (r.get("violations") or [])
                if "blind" in v
            ),
            "stale_applied": sum(
                1 for r in results for v in (r.get("violations") or [])
                if "stale" in v
            ),
            "receipt_fs_mismatch": sum(
                1 for r in results for v in (r.get("violations") or [])
                if "mismatch" in v
            ),
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "qualification_passed": report["qualification_passed"],
        "passed": passed,
        "failed": failed,
        "aborted": aborted,
        "out": str(out),
    }, indent=2))
    return 0 if report["qualification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
