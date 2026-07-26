# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Server-side ledger for agentic code receipts.

Every public `/api/demo/code/run` that finishes seals a `code_receipt` on the
stream. This module persists those receipts to a hash-chained JSONL ledger so
users (and operators) can audit later runs — a concrete switch reason vs
Claude Code / Codex black boxes.

Thread-safe append; tail reads are best-effort. Local/sovereign installs write
under the sandbox root's parent `runs/` when configured, else repo `runs/`.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.Lock()
_LEDGER: Optional[Path] = None


def init(root: Optional[Path] = None) -> Path:
    """Point the ledger at ``<root>/code_receipts.jsonl`` (created on first write)."""
    global _LEDGER
    if root is None:
        env = os.environ.get("LOLM_CODE_RECEIPT_DIR", "").strip()
        if env:
            root = Path(env)
        else:
            root = Path(__file__).resolve().parent.parent / "runs"
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _LEDGER = root / "code_receipts.jsonl"
    return _LEDGER


def ledger_path() -> Path:
    if _LEDGER is None:
        return init()
    return _LEDGER


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:24]


def _last_sha(path: Path) -> Optional[str]:
    try:
        last = None
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        if last:
            return json.loads(last).get("ledger_sha") or json.loads(last).get("receipt_sha")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return None


def append(receipt: Dict[str, Any], *, source: str = "code_run") -> Dict[str, Any]:
    """Append one code receipt; returns the ledger row (with chain fields)."""
    path = ledger_path()
    row = dict(receipt or {})
    row["source"] = source
    row["ledger_ts"] = int(time.time())
    with _LOCK:
        prev = _last_sha(path)
        row["prev_ledger_sha"] = prev
        core = {
            "prev": prev,
            "receipt_sha": row.get("receipt_sha"),
            "task": (row.get("task") or "")[:200],
            "verdict": row.get("verdict"),
            "ok": row.get("ok"),
            "ts": row.get("ledger_ts"),
            "source": source,
        }
        row["ledger_sha"] = _sha(json.dumps(core, sort_keys=True, separators=(",", ":")))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def tail(limit: int = 20) -> List[Dict[str, Any]]:
    """Most recent ledger rows (oldest → newest within the window)."""
    path = ledger_path()
    limit = max(1, min(int(limit or 20), 200))
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    except FileNotFoundError:
        return []
    out: List[Dict[str, Any]] = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def stats() -> Dict[str, Any]:
    rows = tail(200)
    ok_n = sum(1 for r in rows if r.get("ok"))
    return {
        "path": str(ledger_path()),
        "recent": len(rows),
        "ok": ok_n,
        "fail": len(rows) - ok_n,
        "last_sha": (rows[-1].get("ledger_sha") if rows else None),
    }


def ensure_demo_seed() -> bool:
    """If the ledger is empty, seal two labeled demo receipts so the public
    audit page is never a blank wall. Marked ``demo: true`` — not real user runs.
    Returns True if seeds were written.
    """
    if tail(1):
        return False
    samples = [
        {
            "kind": "code_agent",
            "task": "[demo] make hello.py print 42 and run it",
            "summary": "demo seed — print 42",
            "verdict": "shipped",
            "ok": True,
            "files": ["hello.py"],
            "green_runs": 1,
            "failed_runs": 0,
            "verifies": 0,
            "expected": ["42"],
            "expected_ok": True,
            "trail": [
                {"op": "write", "path": "hello.py", "bytes": 12},
                {"op": "run", "command": "python3 hello.py", "exit": 0},
            ],
            "receipt_sha": "demo_code_seed_0001",
            "demo": True,
        },
        {
            "kind": "visual_build",
            "task": "[demo] tiny animated canvas pulse",
            "verdict": "verified",
            "ok": True,
            "attempts": 1,
            "mode": "single",
            "bytes": 1200,
            "working": True,
            "renders": True,
            "animates": True,
            "responds": False,
            "html_sha": "demo_visual_seed_html",
            "receipt_sha": "demo_visual_seed_0001",
            "demo": True,
        },
    ]
    for s in samples:
        append(s, source="demo_seed")
    return True


def ensure_selftest_receipt() -> Optional[Dict[str, Any]]:
    """Seal one *real* non-demo receipt by writing+running code in a temp sandbox.

    Keeps /receipts.html honest: at least one ledger row is a live execute, not
    only ``demo: true`` seeds. Idempotent — skips if a selftest already exists
    in the recent window.
    """
    recent = tail(50)
    if any(r.get("selftest") or r.get("source") == "selftest" for r in recent):
        return None
    try:
        import tempfile
        from local_ui.sandbox import Sandbox
    except Exception:
        return None
    task = "selftest: write hello.py that prints 42 and run it"
    try:
        with tempfile.TemporaryDirectory(prefix="lolm_selftest_") as td:
            sb = Sandbox(Path(td))
            content = "print(42)\n"
            sb.write_file("hello.py", content)
            # Prefer unjailed for host portability; fall back to isolated.
            r = sb.run("python3 hello.py", timeout=10, isolated=None)
            if r.get("exit_code") != 0 or "42" not in (r.get("stdout") or ""):
                r = sb.run("python3 hello.py", timeout=10, isolated=True)
            ok = r.get("exit_code") == 0 and "42" in (r.get("stdout") or "")
            receipt = {
                "kind": "code_agent",
                "task": task,
                "summary": "live selftest — sandbox wrote+ran print(42)",
                "verdict": "shipped" if ok else "incomplete",
                "ok": bool(ok),
                "files": ["hello.py"],
                "green_runs": 1 if ok else 0,
                "failed_runs": 0 if ok else 1,
                "verifies": 0,
                "expected": ["42"],
                "expected_ok": bool(ok),
                "last_stdout_tail": (r.get("stdout") or "")[-200:],
                "trail": [
                    {"op": "write", "path": "hello.py", "bytes": len(content)},
                    {"op": "run", "command": "python3 hello.py",
                     "exit": r.get("exit_code"), "stdout": (r.get("stdout") or "")[:80]},
                ],
                "selftest": True,
                "demo": False,
            }
            # seal receipt_sha like the agent
            core = {
                k: receipt[k] for k in (
                    "task", "summary", "verdict", "ok", "files", "green_runs",
                    "failed_runs", "expected", "expected_ok",
                ) if k in receipt
            }
            receipt["receipt_sha"] = _sha(json.dumps(core, sort_keys=True, separators=(",", ":")))
            return append(receipt, source="selftest")
    except Exception:
        return None
