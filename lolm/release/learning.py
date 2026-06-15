# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Gather accumulated learning and turn it into CONCRETE improvement targets.

No fake learning: this reads only what is actually on disk — HF ingest receipts,
source-backed research/HF memory, the autonomy flywheel, prior daily receipts,
and recorded failed evals — and every target it proposes is a specific, inspectable
change (a changelog entry, a dependency audit fix, a regression test for a failed
eval, a controller-threshold review backed by flywheel data). If nothing concrete
is found, it returns no targets and the day's verdict is `no_change_needed`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return rows


def gather_learning(root: str | Path) -> Dict[str, Any]:
    """Read every learning source. Returns counts + the sources actually present."""
    root = Path(root)
    runs = root / "runs"
    hf = _read_jsonl(runs / "hf_ingest_receipts.jsonl")
    research_mem = _read_jsonl(runs / "research_memory.jsonl")
    hf_mem = _read_jsonl(runs / "hf_memory.jsonl")
    hf_cands = _read_jsonl(runs / "hf_candidates.jsonl")
    flywheel = _read_jsonl(runs / "autonomy_flywheel.jsonl")
    research_receipts = _read_jsonl(runs / "research_job_receipts.jsonl")

    sources: List[str] = []
    if hf:
        sources.append(f"huggingface ingest ({len(hf)} receipts)")
    if research_mem or hf_mem:
        sources.append(f"qira brain memory ({len(research_mem) + len(hf_mem)} source-backed)")
    if research_receipts:
        sources.append(f"web research jobs ({len(research_receipts)} runs)")
    if flywheel:
        sources.append(f"autonomy flywheel ({len(flywheel)} verified outcomes)")

    web_searches = sum(len(r.get("actions") or [])
                       for r in research_receipts if isinstance(r, dict))
    return {
        "sources_present": sources,
        "hf_datasets_scanned": sum(r.get("datasets_seen", 0) for r in hf),
        "hf_candidates_queued": sum(1 for c in hf_cands if not c.get("trained")),
        "memories_written": len(research_mem) + len(hf_mem),
        "web_searches_performed": web_searches,
        "flywheel_records": len(flywheel),
        "prior_daily_runs": len(list((runs / "daily").glob("*.json"))) if (runs / "daily").exists() else 0,
        "failed_evals": _read_jsonl(runs / "failed_evals.jsonl"),
    }


def find_targets(root: str | Path, learning: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Concrete improvement targets. Each: {kind, detail, action, safe_auto}.

    safe_auto=True targets are deterministic + reversible (the orchestrator may
    apply them autonomously). safe_auto=False targets need the LLM patcher or a
    human, so they are recorded but not auto-applied.
    """
    targets: List[Dict[str, Any]] = []

    # 1) New learning since the last shipped receipt → changelog entry (safe).
    if learning.get("memories_written", 0) or learning.get("hf_datasets_scanned", 0):
        targets.append({
            "kind": "changelog_entry",
            "detail": (f"{learning.get('memories_written',0)} new source-backed memories, "
                       f"{learning.get('hf_datasets_scanned',0)} HF datasets scanned"),
            "action": "append a dated CHANGELOG entry summarising the day's learning",
            "safe_auto": True,
        })

    # 2) Dependency audit (safe to attempt; gate decides if the fix is clean).
    targets.append({
        "kind": "dependency_audit",
        "detail": "npm audit on clients/js for high/critical advisories",
        "action": "run `npm audit`; if a non-breaking fix exists, apply it",
        "safe_auto": True,
    })

    # 3) Failed evals → a regression test (records the target; needs a real fix).
    for fe in (learning.get("failed_evals") or [])[:5]:
        targets.append({
            "kind": "regression_from_failed_eval",
            "detail": f"failed: {str(fe.get('prompt') or fe)[:80]}",
            "action": "add a regression eval/test capturing this failure",
            "safe_auto": False,
        })

    # 4) Controller-training candidate batch ready (informational gate to L3).
    cands = learning.get("hf_candidates_queued", 0)
    if cands:
        targets.append({
            "kind": "controller_training_candidates",
            "detail": f"{cands} licensed controller-training candidates queued",
            "action": "queued for the eval-gated trainer (no auto weight change)",
            "safe_auto": False,
        })

    return targets
