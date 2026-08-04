# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Verifier dataset: does the evidence support shipment?

Keeping the verifier separate reduces the risk that the generator simply learns
to approve its own work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lolm.evolution.schema import (
    VerifierExample,
    VerifierLabel,
    default_paths,
    read_jsonl,
    sha256_file,
    write_jsonl,
)


def label_from_row(row: Dict[str, Any]) -> str:
    ver = row.get("verification") or {}
    oracle = str(row.get("independent_oracle") or "").lower()
    verdict = str(ver.get("verdict") or row.get("verdict") or "").lower()
    reasons = [str(x).lower() for x in (ver.get("reasons") or row.get("reasons") or [])]

    if row.get("trust_abort"):
        return VerifierLabel.UNSAFE.value
    if "false" in verdict or "false_green" in reasons or "false_green" in verdict:
        return VerifierLabel.FALSE_GREEN.value
    if "regress" in " ".join(reasons) or "regress" in verdict:
        return VerifierLabel.REGRESSION.value
    if "unsupported" in " ".join(reasons):
        return VerifierLabel.UNSUPPORTED.value
    if oracle == "pass" or verdict in ("verified", "pass", "ok", "green"):
        return VerifierLabel.VERIFIED.value
    if oracle == "fail" or verdict in ("failed", "fail", "red"):
        # incomplete vs false_green: if model claimed done
        claimed = _claimed_done(row)
        if claimed:
            return VerifierLabel.FALSE_GREEN.value
        return VerifierLabel.INCOMPLETE.value
    return VerifierLabel.INCOMPLETE.value


def _claimed_done(row: Dict[str, Any]) -> bool:
    for m in row.get("messages") or []:
        if str(m.get("role")).lower() == "assistant":
            c = str(m.get("content") or "").lower()
            if "done" in c or "verified" in c or "fixed" in c:
                return True
    return False


def example_from_row(row: Dict[str, Any]) -> VerifierExample:
    ver = row.get("verification") or {}
    test_out = "\n".join(str(x) for x in (row.get("stdout") or [])[:20])
    if not test_out and ver:
        test_out = str(ver)
    return VerifierExample(
        task_contract=str(row.get("task") or "")[:2000],
        diff=str(row.get("diff") or row.get("mutations_applied") or "")[:4000],
        test_output=test_out[:4000],
        artifact=str(row.get("final_tree_hash") or row.get("html_sha") or "")[:500],
        receipt_summary=str({
            "oracle": row.get("independent_oracle"),
            "signature_valid": row.get("receipt_signature_valid"),
            "trust_abort": row.get("trust_abort"),
            "verdict": ver.get("verdict"),
        })[:1000],
        claimed_completion=_assistant_tail(row),
        label=label_from_row(row),
        trajectory_id=str(row.get("trajectory_id") or ""),
    )


def _assistant_tail(row: Dict[str, Any]) -> str:
    for m in reversed(row.get("messages") or []):
        if str(m.get("role")).lower() == "assistant":
            return str(m.get("content") or "")[:1000]
    return ""


def build_verifier_dataset(
    rows: Sequence[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
    out_name: str = "verifier.jsonl",
) -> Dict[str, Any]:
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    paths = default_paths(repo_root)
    examples = [example_from_row(r).to_dict() for r in rows]
    out = paths.datasets / out_name
    write_jsonl(out, examples)
    counts: Dict[str, int] = {}
    for e in examples:
        counts[e["label"]] = counts.get(e["label"], 0) + 1
    return {
        "path": str(out),
        "count": len(examples),
        "label_counts": counts,
        "dataset_sha256": sha256_file(out) if out.exists() else "",
    }


def build_verifier_from_repo(repo_root: Path) -> Dict[str, Any]:
    paths = default_paths(repo_root)
    # Use silver for both pass and fail labels; gold alone is pass-skewed
    silver = read_jsonl(paths.silver / "silver_latest.jsonl")
    gold = read_jsonl(paths.gold / "gold_latest.jsonl")
    return build_verifier_dataset(silver + gold, repo_root=repo_root)
