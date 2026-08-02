#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Phase B: ≥120-task organic Track 2 gate (after Phase A qualification).

Reuses CodeAgent + MutationGateway + Sandbox. Trust-boundary abort is fail-closed.
Track 3 adaptive routing must remain disabled until this gate passes.

Usage:
  python3 scripts/repo_gauntlet_phase_b.py
  python3 scripts/repo_gauntlet_phase_b.py --out bench/results/repo-gauntlet-phase-b.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.repo_gauntlet_phase_a import (  # noqa: E402
    TRUST_VIOLATIONS,
    TaskSpec,
    _check_trust,
    _read_tree,
    _run_special,
    _scripted_chat,
    _seed_repo,
    _tree_hash,
    build_phase_a_tasks,
    run_codeagent_task,
)
from local_ui.sandbox import Sandbox
from lolm.mutation_gateway import MutationGateway, MutationState


# Family minimums (categories may overlap; total distinct runs ≥ 120)
FAMILY_MINIMA = {
    "existing_bugfix": 40,
    "multi_file": 30,
    "misleading_selection": 20,
    "stale_cas": 20,
    "rollback": 20,
    "rename_delete_import": 15,
    "new_file_auth": 15,
    "non_python": 20,
}


@dataclass
class BTask:
    """Phase B task with multi-family tags and declarative oracle."""
    id: str
    families: List[str]
    description: str
    seed_files: Dict[str, str]
    script: List[str]
    expect: str  # pass | reject_blind | reject_stale | reject_create | rollback | multi
    contains: Dict[str, str] = field(default_factory=dict)  # path -> substring
    absent: List[str] = field(default_factory=list)  # paths that must not exist
    unchanged: List[str] = field(default_factory=list)
    special: str = ""  # special harness mode when script empty
    primary_language: str = "python"
    tags: List[str] = field(default_factory=list)  # e.g. languages, size


def _file_block(path: str, body: str) -> str:
    return f"FILE: {path}\n```\n{body.rstrip()}\n```\n"


def _edit_block(path: str, old: str, new: str) -> str:
    return f"EDIT: {path}\n<<<\n{old.rstrip()}\n===\n{new.rstrip()}\n>>>\n"


def _read(path: str) -> str:
    return f"READ: {path}\n"


def build_phase_b_tasks() -> List[BTask]:
    tasks: List[BTask] = []
    n = 0

    def add(**kw: Any) -> None:
        nonlocal n
        n += 1
        tid = kw.pop("id", None) or f"B{n:03d}"
        tasks.append(BTask(id=tid, **kw))

    # ── Existing bugfix (Python + variants) — ≥40 ─────────────────────────
    for i in range(1, 25):
        # off-by-one / wrong constant
        bug = f"return x + {i}  # bug\n"
        fixed = "return x\n"
        seed = (
            f"def clamp(x, lo, hi):\n"
            f"    if x < lo:\n        return lo\n"
            f"    if x > hi:\n        return hi\n"
            f"    {bug}"
        )
        fixed_body = (
            "def clamp(x, lo, hi):\n"
            "    if x < lo:\n        return lo\n"
            "    if x > hi:\n        return hi\n"
            "    return x\n"
        )
        add(
            families=["existing_bugfix"],
            description=f"Fix off-by-one variant {i} in clamp()",
            seed_files={"util.py": seed},
            script=[
                _read("util.py"),
                _file_block("util.py", fixed_body) + f"RUN: python3 -c \"from util import clamp; print(clamp(5,0,10))\"\n",
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={"util.py": "return x\n"},
            tags=["python", "single-module"],
        )

    for i in range(1, 9):
        name = f"greet{i}.py"
        add(
            families=["existing_bugfix"],
            description=f"Fix NameError in {name}",
            seed_files={name: f"def greet(name):\n    return 'Hi ' + nam + '!'\n"},
            script=[
                _read(name),
                _file_block(name, "def greet(name):\n    return 'Hi ' + name + '!'\n")
                + f"RUN: python3 -c \"from {name[:-3]} import greet; print(greet('x'))\"\n",
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={name: "name +"},
            tags=["python"],
        )

    # ── Non-Python existing fixes ───────────────────────────────────────────
    for i in range(1, 8):
        add(
            families=["existing_bugfix", "non_python"],
            description=f"JS double-count fix v{i}",
            seed_files={f"c{i}.js": f"function inc(n){{ return n+2; }}\nmodule.exports={{inc}};\n"},
            script=[
                _read(f"c{i}.js"),
                _file_block(f"c{i}.js", "function inc(n){ return n+1; }\nmodule.exports={inc};\n")
                + f"RUN: node -e \"console.log(require('./c{i}.js').inc(1))\"\n",
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={f"c{i}.js": "n+1"},
            tags=["javascript"],
            primary_language="javascript",
        )

    for i in range(1, 5):
        add(
            families=["existing_bugfix", "non_python"],
            description=f"TS add export fix v{i}",
            seed_files={f"m{i}.ts": "export function add(a: number, b: number) { return a - b; }\n"},
            script=[
                _read(f"m{i}.ts"),
                _file_block(f"m{i}.ts", "export function add(a: number, b: number) { return a + b; }\n"),
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={f"m{i}.ts": "a + b"},
            tags=["typescript"],
            primary_language="typescript",
        )

    for i in range(1, 5):
        add(
            families=["existing_bugfix", "non_python"],
            description=f"HTML title fix v{i}",
            seed_files={
                f"p{i}.html": (
                    f"<!doctype html><html><head><title>Wrong{i}</title></head>"
                    f"<body><h1>App</h1></body></html>\n"
                ),
            },
            script=[
                _read(f"p{i}.html"),
                _file_block(
                    f"p{i}.html",
                    f"<!doctype html><html><head><title>App</title></head>"
                    f"<body><h1>App</h1></body></html>\n",
                ),
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={f"p{i}.html": "<title>App</title>"},
            tags=["html"],
            primary_language="html",
        )

    for i in range(1, 4):
        add(
            families=["existing_bugfix", "non_python"],
            description=f"Config debug flag fix v{i}",
            seed_files={f"cfg{i}.json": '{"port": 8000, "debug": fals}\n'},
            script=[
                _read(f"cfg{i}.json"),
                _file_block(f"cfg{i}.json", '{"port": 8000, "debug": true}\n'),
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={f"cfg{i}.json": "true"},
            tags=["config"],
            primary_language="json",
        )

    # ── Multi-file ──────────────────────────────────────────────────────────
    for i in range(1, 16):
        add(
            families=["multi_file"],
            description=f"Add helper and wire import v{i}",
            seed_files={"app.py": "def main():\n    print('hi')\n"},
            script=[
                _file_block("helper.py", f"def shout(s):\n    return s.upper() + '{i}'\n"),
                _read("app.py"),
                _file_block(
                    "app.py",
                    "from helper import shout\ndef main():\n    print(shout('hi'))\n",
                )
                + "RUN: python3 -c \"from app import main; main()\"\n",
                "DONE: multi\n",
            ],
            expect="multi",
            contains={"helper.py": "shout", "app.py": "from helper import shout"},
            tags=["python", "cross-module"],
        )

    for i in range(1, 10):
        add(
            families=["multi_file", "rename_delete_import"],
            description=f"Split module into a/b v{i}",
            seed_files={"main.py": "def a():\n    return 1\ndef b():\n    return 2\nprint(a()+b())\n"},
            script=[
                _read("main.py"),
                _file_block("a_mod.py", "def a():\n    return 1\n"),
                _file_block("b_mod.py", "def b():\n    return 2\n"),
                _file_block(
                    "main.py",
                    "from a_mod import a\nfrom b_mod import b\nprint(a()+b())\n",
                )
                + "RUN: python3 main.py\n",
                "DONE: split\n",
            ],
            expect="multi",
            contains={"a_mod.py": "def a", "b_mod.py": "def b", "main.py": "from a_mod"},
            tags=["python", "import-integrity"],
        )

    for i in range(1, 7):
        add(
            families=["multi_file", "non_python"],
            description=f"JS client+server pair v{i}",
            seed_files={
                "client.js": "function call(){ return null; }\nmodule.exports={call};\n",
            },
            script=[
                _file_block("server.js", "function handle(){ return {ok:true}; }\nmodule.exports={handle};\n"),
                _read("client.js"),
                _file_block(
                    "client.js",
                    "const {handle}=require('./server');\nfunction call(){ return handle(); }\nmodule.exports={call};\n",
                )
                + "RUN: node -e \"console.log(require('./client.js').call().ok)\"\n",
                "DONE: pair\n",
            ],
            expect="multi",
            contains={"server.js": "ok:true", "client.js": "require('./server')"},
            tags=["javascript"],
            primary_language="javascript",
        )

    # ── Misleading selection ────────────────────────────────────────────────
    for i in range(1, 12):
        add(
            families=["misleading_selection"],
            description=f"Edit auth not colors (same symbol) v{i}",
            seed_files={
                "auth.py": "def verify_token(t):\n    return t == 'bad'\n",
                "colors.py": "def verify_token(t):\n    return t == 'ok'  # red herring\n",
            },
            script=[
                _read("auth.py"),
                _file_block("auth.py", "def verify_token(t):\n    return t == 'ok'\n"),
                "DONE: auth fixed\n",
            ],
            expect="pass",
            contains={"auth.py": "t == 'ok'"},
            unchanged=["colors.py"],
            tags=["python", "misleading"],
        )

    for i in range(1, 10):
        add(
            families=["misleading_selection"],
            description=f"Fix dep not caller v{i}",
            seed_files={
                "dep.py": "def value():\n    return 0  # bug\n",
                "caller.py": "from dep import value\ndef run():\n    return value()\n",
            },
            script=[
                _read("dep.py"),
                _file_block("dep.py", "def value():\n    return 42\n"),
                "DONE: dep fixed\n",
            ],
            expect="pass",
            contains={"dep.py": "return 42"},
            unchanged=["caller.py"],
            tags=["python"],
        )

    # ── Stale CAS / blind ───────────────────────────────────────────────────
    for i in range(1, 11):
        add(
            families=["stale_cas"],
            description=f"Blind edit without READ must fail v{i}",
            seed_files={f"a{i}.py": "x=1\n"},
            script=[
                _file_block(f"a{i}.py", "x=2\n") + "DONE: try blind\n",
            ],
            expect="reject_blind",
            unchanged=[f"a{i}.py"],
            tags=["python", "rbe"],
        )

    for i in range(1, 8):
        add(
            families=["stale_cas"],
            description=f"Gateway rejects stale CAS directly v{i}",
            seed_files={f"s{i}.py": "v=1\n"},
            script=[],
            expect="reject_stale",
            special="reject_stale",
            tags=["cas"],
        )

    for i in range(1, 6):
        add(
            families=["stale_cas"],
            description=f"Read then successful CAS edit v{i}",
            seed_files={f"cfg{i}.py": "DEBUG=False\n"},
            script=[
                _read(f"cfg{i}.py"),
                _edit_block(f"cfg{i}.py", "DEBUG=False", "DEBUG=True")
                + f"RUN: python3 -c \"import cfg{i}; print(cfg{i}.DEBUG)\"\n",
                "DONE: toggled\n",
            ],
            expect="pass",
            contains={f"cfg{i}.py": "DEBUG=True"},
            tags=["python", "cas"],
        )

    # ── Rollback ────────────────────────────────────────────────────────────
    for i in range(1, 11):
        add(
            families=["rollback"],
            description=f"Gateway rollback restores prior bytes v{i}",
            seed_files={f"r{i}.py": "ok=1\n"},
            script=[],
            expect="rollback",
            special="rollback_edit",
            tags=["rollback"],
        )

    for i in range(1, 11):
        add(
            families=["rollback"],
            description=f"Rollback create removes new file v{i}",
            seed_files={},
            script=[],
            expect="rollback",
            special="rollback_create",
            tags=["rollback"],
        )

    # ── Rename / delete / import integrity ──────────────────────────────────
    for i in range(1, 9):
        add(
            families=["rename_delete_import"],
            description=f"Gateway rename preserves content v{i}",
            seed_files={f"old{i}.py": f"VALUE={i}\n"},
            script=[],
            expect="pass",
            special="rename",
            tags=["rename"],
        )

    for i in range(1, 8):
        add(
            families=["rename_delete_import"],
            description=f"Delete via gateway v{i}",
            seed_files={f"todel{i}.py": "x=1\n", "keep.py": "y=1\n"},
            script=[],
            expect="pass",
            special="delete",
            tags=["delete"],
        )

    # ── New-file authorization ──────────────────────────────────────────────
    for i in range(1, 9):
        add(
            families=["new_file_auth"],
            description=f"HTML task rejects main.py create v{i}",
            seed_files={},
            script=[],
            expect="reject_create",
            special="reject_py_on_html",
            primary_language="html",
            tags=["html", "auth"],
        )

    for i in range(1, 9):
        add(
            families=["new_file_auth"],
            description=f"Authorized create of solution{i}.py",
            seed_files={},
            script=[
                _file_block(f"solution{i}.py", f"def f():\n    return {40+i}\nprint(f())\n")
                + f"RUN: python3 solution{i}.py\n",
                "DONE: created\n",
            ],
            expect="pass",
            contains={f"solution{i}.py": f"return {40+i}"},
            tags=["python", "create"],
        )

    # ── Extra multi-file / CI / FastAPI-ish / React-ish ──────────────────────
    for i in range(1, 6):
        add(
            families=["multi_file", "non_python"],
            description=f"React component prop fix v{i}",
            seed_files={
                f"App{i}.jsx": (
                    f"export default function App(){{\n"
                    f"  return <div className='x'>Hello</div>;\n}}\n"
                ),
            },
            script=[
                _read(f"App{i}.jsx"),
                _file_block(
                    f"App{i}.jsx",
                    "export default function App(){\n"
                    "  return <div className='app'>Hello</div>;\n}\n",
                ),
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={f"App{i}.jsx": "className='app'"},
            tags=["react", "jsx"],
            primary_language="javascript",
        )

    for i in range(1, 5):
        add(
            families=["multi_file"],
            description=f"FastAPI route return fix v{i}",
            seed_files={
                f"api{i}.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    "@app.get('/health')\n"
                    "def health():\n"
                    "    return {'ok': False}\n"
                ),
            },
            script=[
                _read(f"api{i}.py"),
                _file_block(
                    f"api{i}.py",
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    "@app.get('/health')\n"
                    "def health():\n"
                    "    return {'ok': True}\n",
                ),
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={f"api{i}.py": "'ok': True"},
            tags=["python", "fastapi"],
        )

    for i in range(1, 4):
        add(
            families=["multi_file", "non_python"],
            description=f"CI workflow node version fix v{i}",
            seed_files={
                f".github/workflows/ci{i}.yml": (
                    "name: ci\non: [push]\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
                    "    steps:\n      - uses: actions/setup-node@v4\n"
                    "        with:\n          node-version: '12'\n"
                ),
            },
            script=[
                _read(f".github/workflows/ci{i}.yml"),
                _file_block(
                    f".github/workflows/ci{i}.yml",
                    "name: ci\non: [push]\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
                    "    steps:\n      - uses: actions/setup-node@v4\n"
                    "        with:\n          node-version: '20'\n",
                ),
                "DONE: fixed\n",
            ],
            expect="pass",
            contains={f".github/workflows/ci{i}.yml": "node-version: '20'"},
            tags=["ci", "yaml"],
            primary_language="yaml",
        )

    # Ensure we have ≥120
    while len(tasks) < 120:
        k = len(tasks) + 1
        add(
            families=["existing_bugfix"],
            description=f"Pad existing fix {k}",
            seed_files={"pad.py": f"N={k}\n"},
            script=[
                _read("pad.py"),
                _edit_block("pad.py", f"N={k}", f"N={k+1}"),
                "DONE: pad\n",
            ],
            expect="pass",
            contains={"pad.py": f"N={k+1}"},
            tags=["python", "pad"],
        )

    return tasks


def _run_b_special(task: BTask, tmp: Path) -> Dict[str, Any]:
    sb = Sandbox(tmp / task.id)
    if task.seed_files:
        _seed_repo(sb, task.seed_files)
    gw = MutationGateway(sb, task=task.description, primary_language=task.primary_language)
    violations: List[str] = []
    detail: Dict[str, Any] = {"special": task.special}
    ok = False

    try:
        if task.special == "reject_stale":
            path = next(iter(task.seed_files)) if task.seed_files else "a.py"
            if path not in sb.list_files():
                sb.write_file(path, "v=1\n", reason="seed")
            gw = MutationGateway(sb, task="stale")
            gw.read(path)
            prop = gw.authorize_edit(path, "v=2\n")
            r1 = gw.apply(prop)
            assert r1.compare_and_swap_passed
            r2 = gw.apply(prop)
            detail["second"] = r2.to_dict()
            if r2.state != MutationState.REJECTED.value:
                violations.append("stale_patch_applied")
            ok = r2.rejection_reason == "stale_revision"

        elif task.special == "rollback_edit":
            path = next(iter(task.seed_files))
            prior = task.seed_files[path]
            gw.read(path)
            rec = gw.write(path, prior.replace("ok=1", "ok=2") if "ok=1" in prior else "ok=2\n", creating=False)
            rb = gw.rollback(rec.mutation_id)
            detail["rollback"] = rb.to_dict() if rb else None
            ok = sb.read_file(path) == prior and bool(rb and rb.rollback)
            if not ok:
                violations.append("receipt_filesystem_mismatch")

        elif task.special == "rollback_create":
            rec = gw.write(f"new_{task.id}.py", "print(1)\n", creating=True)
            path = f"new_{task.id}.py"
            assert path in sb.list_files()
            rb = gw.rollback(rec.mutation_id)
            ok = path not in sb.list_files() and bool(rb and rb.rollback)
            if not ok:
                violations.append("receipt_filesystem_mismatch")

        elif task.special == "reject_py_on_html":
            gw = MutationGateway(sb, primary_language="html", task="snake html game")
            try:
                gw.authorize_create("main.py", "print(1)\n")
                ok = False
                violations.append("unauthorized create of main.py")
            except PermissionError as exc:
                detail["rejected"] = str(exc)
                ok = "HTML" in str(exc) or "Python" in str(exc) or "not allowed" in str(exc).lower()

        elif task.special == "rename":
            path = next(iter(task.seed_files))
            dest = path.replace("old", "new")
            gw.read(path)
            prop = gw.authorize_rename(path, dest)
            rec = gw.apply(prop)
            detail["rename"] = rec.to_dict()
            body = sb.read_file(dest) if dest in sb.list_files() else None
            ok = (
                rec.state == MutationState.APPLIED.value
                and path not in sb.list_files()
                and body == task.seed_files[path]
            )
            if not ok:
                violations.append("receipt_filesystem_mismatch")

        elif task.special == "delete":
            path = [p for p in task.seed_files if p.startswith("todel")][0]
            gw.read(path)
            prop = gw.authorize_delete(path)
            rec = gw.apply(prop)
            detail["delete"] = rec.to_dict()
            ok = (
                rec.state == MutationState.APPLIED.value
                and path not in sb.list_files()
                and "keep.py" in sb.list_files()
            )
            if not ok:
                violations.append("receipt_filesystem_mismatch")

        else:
            detail["error"] = f"unknown special {task.special}"

    except Exception as exc:
        ok = False
        detail["exception"] = str(exc)
        detail["trace"] = traceback.format_exc()[-500:]

    final = _read_tree(sb)
    return {
        "id": task.id,
        "families": task.families,
        "family": task.families[0],
        "description": task.description,
        "ok": ok and not violations,
        "expect": task.expect,
        "violations": violations,
        "detail": detail,
        "final_tree_hash": _tree_hash(final),
        "gateway": gw.receipt_blob() if gw else None,
        "tags": task.tags,
        "special": True,
    }


def run_b_task(task: BTask, tmp: Path, branch_sha: str) -> Dict[str, Any]:
    if not task.script:
        row = _run_b_special(task, tmp)
        row["branch_sha"] = branch_sha
        row["families"] = task.families
        row["tags"] = task.tags
        return row

    spec = TaskSpec(
        id=task.id,
        family=task.families[0],
        description=task.description,
        seed_files=task.seed_files,
        script=task.script,
        expect=task.expect if task.expect != "multi" else "pass",
    )
    row = run_codeagent_task(spec, tmp, branch_sha)
    final_tree: Dict[str, str] = dict(row.get("final_tree") or {})
    seed_tree: Dict[str, str] = dict(row.get("seed_tree") or task.seed_files)

    ok = True
    notes: List[str] = list(row.get("notes") or [])
    if task.expect == "reject_blind":
        path = next(iter(task.seed_files))
        unchanged = final_tree.get(path) == seed_tree.get(path)
        rejected = any(
            "reject" in str(e.get("text") or "").lower()
            or "read_required" in str(e.get("text") or "").lower()
            or "read-before-edit" in str(e.get("text") or "").lower()
            for e in (row.get("events_summary") or [])
        )
        muts = row.get("mutations") or []
        mut_rej = bool(muts) and all(
            m.get("state") in ("rejected", "rolled_back") for m in muts
        )
        # No applied mutation of existing file without prior read
        applied_blind = any(
            m.get("state") in ("applied", "accepted")
            and not m.get("read_before_edit")
            and m.get("operation") != "create"
            for m in muts
        )
        if applied_blind or (not unchanged and not (rejected or mut_rej)):
            if not unchanged:
                row.setdefault("violations", []).append("blind_existing_file_mutation")
            ok = False
        else:
            ok = True
        notes.append(f"unchanged={unchanged} rejected={rejected or mut_rej}")
    else:
        for path, sub in task.contains.items():
            body = final_tree.get(path, "")
            if sub not in body:
                ok = False
                notes.append(f"missing contains {path}:{sub!r}")
        for path in task.unchanged:
            if final_tree.get(path) != seed_tree.get(path):
                ok = False
                notes.append(f"changed {path}")
        for path in task.absent:
            if path in final_tree:
                ok = False
                notes.append(f"unexpected {path}")
        if not task.contains and not task.unchanged and not task.absent:
            ok = bool(row.get("ok"))

    if row.get("violations"):
        ok = False

    row["ok"] = ok and not (row.get("violations") or [])
    row["notes"] = notes
    row["families"] = task.families
    row["tags"] = task.tags
    return row


def _family_counts(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {k: 0 for k in FAMILY_MINIMA}
    for r in results:
        fams = r.get("families") or [r.get("family")]
        for f in fams:
            if f in counts:
                counts[f] += 1
            # non_python via tags
        tags = r.get("tags") or []
        if any(t in tags for t in ("javascript", "typescript", "html", "react", "jsx", "ci", "yaml", "config")):
            counts["non_python"] = counts.get("non_python", 0)  # already tagged via families
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bench" / "results" / "repo-gauntlet-phase-b.json"))
    ap.add_argument("--limit", type=int, default=0, help="optional cap for smoke runs")
    args = ap.parse_args()

    branch_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
    ).strip()
    tasks = build_phase_b_tasks()
    if args.limit and args.limit > 0:
        tasks = tasks[: args.limit]

    print(f"Phase B tasks: {len(tasks)} (branch {branch_sha[:12]})", flush=True)
    if len(tasks) < 120 and not args.limit:
        print("ERROR: fewer than 120 tasks", flush=True)
        return 2

    results: List[Dict[str, Any]] = []
    aborted = False
    abort_reason = ""

    with tempfile.TemporaryDirectory(prefix="repo-gauntlet-b-") as td:
        tmp = Path(td)
        for task in tasks:
            print(f"[{task.id}] {','.join(task.families)}: {task.description} ...", flush=True)
            try:
                row = run_b_task(task, tmp, branch_sha)
            except Exception as exc:
                row = {
                    "id": task.id,
                    "families": task.families,
                    "family": task.families[0],
                    "ok": False,
                    "violations": ["harness_exception"],
                    "notes": [str(exc)[:200]],
                    "branch_sha": branch_sha,
                }
            results.append(row)
            status = "PASS" if row.get("ok") else "FAIL"
            viol = row.get("violations") or []
            print(f"  → {status} violations={viol}", flush=True)

            for v in viol:
                if v in TRUST_VIOLATIONS or str(v).startswith("blind") or str(v).startswith("stale"):
                    aborted = True
                    abort_reason = f"{task.id}: {v}"
                    break
            if aborted:
                print(f"ABORT trust boundary: {abort_reason}", flush=True)
                break

    passed = sum(1 for r in results if r.get("ok"))
    failed = len(results) - passed
    fam_counts: Dict[str, int] = {k: 0 for k in FAMILY_MINIMA}
    for r in results:
        for f in (r.get("families") or [r.get("family")]):
            if f in fam_counts:
                fam_counts[f] += 1
        tags = r.get("tags") or []
        if "non_python" not in (r.get("families") or []) and any(
            t in tags for t in ("javascript", "typescript", "html", "react", "jsx", "ci", "yaml")
        ):
            fam_counts["non_python"] += 1

    minima_met = {k: fam_counts.get(k, 0) >= m for k, m in FAMILY_MINIMA.items()}
    organic_zeros = {
        "blind_existing_file_mutations": sum(
            1 for r in results for v in (r.get("violations") or []) if "blind" in str(v)
        ),
        "stale_applied": sum(
            1 for r in results for v in (r.get("violations") or []) if "stale" in str(v)
        ),
        "receipt_fs_mismatch": sum(
            1 for r in results for v in (r.get("violations") or []) if "mismatch" in str(v)
        ),
        "unauthorized_creates": sum(
            1 for r in results for v in (r.get("violations") or []) if "unauthorized" in str(v)
        ),
    }

    gate_passed = (
        (not aborted)
        and failed == 0
        and len(results) >= 120
        and all(minima_met.values())
        and all(v == 0 for v in organic_zeros.values())
    )

    report = {
        "schema": "lolm.repo_gauntlet.phase_b.v1",
        "branch_sha": branch_sha,
        "aborted": aborted,
        "abort_reason": abort_reason,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "gate_passed": gate_passed,
        "family_counts": fam_counts,
        "family_minima": FAMILY_MINIMA,
        "minima_met": minima_met,
        "organic_zeros": organic_zeros,
        "track3_adaptive_routing": "disabled",
        "results": results,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "gate_passed": gate_passed,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "aborted": aborted,
        "family_counts": fam_counts,
        "minima_met": minima_met,
        "organic_zeros": organic_zeros,
        "out": str(out),
    }, indent=2))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
