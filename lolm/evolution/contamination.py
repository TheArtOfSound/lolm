# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Benchmark contamination checks for evolution datasets.

We refuse to train on prompts that match known public benchmark stems or
exact eval fixtures shipped with the repo. Expand BENCHMARK_STEMS over time.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

# Lightweight public-bench stems (extend; not a full decontamination suite).
BENCHMARK_STEMS: Sequence[str] = (
    "def is_prime",
    "write a function that returns the nth fibonacci",
    "the capital of france is",
    "humaneval",
    "mbpp",
    "swe-bench",
    "livecodebench",
    "mmlu",
    "hellaswag",
    "gsm8k",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def load_fixture_hashes(repo_root: Optional[Path] = None) -> Set[str]:
    """Hash known local eval prompts so we do not train on our own suite."""
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    hashes: Set[str] = set()
    candidates = [
        root / "evals",
        root / "bench",
        root / "tests",
        root / "runs" / "failed_evals.jsonl",
    ]
    for c in candidates:
        if c.is_file() and c.suffix == ".jsonl":
            try:
                for line in c.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.strip():
                        hashes.add(hashlib.sha256(line.encode()).hexdigest())
                        # also hash prompt field if JSON
                        if '"prompt"' in line or '"task"' in line:
                            import json
                            try:
                                d = json.loads(line)
                                for k in ("prompt", "task", "command"):
                                    if d.get(k):
                                        hashes.add(hashlib.sha256(_norm(str(d[k])).encode()).hexdigest())
                            except Exception:
                                pass
            except OSError:
                pass
        elif c.is_dir():
            for p in c.rglob("*.jsonl"):
                try:
                    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()[:5000]:
                        if not line.strip():
                            continue
                        hashes.add(hashlib.sha256(_norm(line).encode()).hexdigest())
                except OSError:
                    continue
    return hashes


def is_contaminated(
    task: str,
    *,
    fixture_hashes: Optional[Set[str]] = None,
    stems: Sequence[str] = BENCHMARK_STEMS,
) -> bool:
    n = _norm(task)
    if not n:
        return False
    for stem in stems:
        if stem in n:
            return True
    if fixture_hashes is not None:
        h = hashlib.sha256(n.encode()).hexdigest()
        if h in fixture_hashes:
            return True
    return False


def mark_contamination(
    rows: Sequence[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fixtures = load_fixture_hashes(repo_root)
    out: List[Dict[str, Any]] = []
    n_bad = 0
    for r in rows:
        bad = is_contaminated(str(r.get("task") or ""), fixture_hashes=fixtures)
        r = dict(r)
        r["benchmark_contaminated"] = bad
        if bad:
            n_bad += 1
        out.append(r)
    return out, {"checked": len(rows), "contaminated": n_bad}
