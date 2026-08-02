# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Artifact Closure Protocol (ACP).

Closure requires independent hashing and inspection of actual artifact bytes.
Caller-supplied booleans or hashes are never authoritative alone.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from lolm.reliability.evidence import content_sha256, hash_tree, pdf_bytes_valid


@dataclass
class ClosureResult:
    ready: bool
    reason: str
    closed: bool = False
    checkpoint_id: str = ""
    manifest: Dict[str, Any] = field(default_factory=dict)
    blocked_model_turns: int = 0
    preconditions: Dict[str, bool] = field(default_factory=dict)
    independent_hashes: Dict[str, str] = field(default_factory=dict)
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_closure(
    *,
    file_contents: Optional[Mapping[str, Union[str, bytes]]] = None,
    contract_ok: bool,
    exact_manifest_ok: bool,
    validators_green: bool,
    open_hard: int,
    contradictory: bool = False,
    receipt_signable: bool = True,
    deliverable_paths: Optional[Sequence[str]] = None,
    claimed_hashes: Optional[Dict[str, str]] = None,
    primary_language: str = "",
) -> ClosureResult:
    """Pure predicate with independent byte evidence.

    ``file_contents`` is required for ready=True. Hashes are computed here.
    ``claimed_hashes`` if provided must match independent hashes or closure fails.
    """
    contents = dict(file_contents or {})
    paths = list(deliverable_paths or contents.keys())
    independent = hash_tree(contents) if contents else {}

    has_contents = bool(contents) and all(p in contents for p in paths if p)
    hashes_complete = bool(independent) and all(
        independent.get(p) for p in paths if p
    )
    # Every deliverable must have a non-empty body with authoritative hash
    nonempty = all(
        (isinstance(contents.get(p), (bytes, bytearray)) and len(contents[p]) > 0)
        or (isinstance(contents.get(p), str) and len(contents.get(p) or "") > 0)
        for p in paths if p
    ) if paths else False

    claim_match = True
    claim_why = ""
    if claimed_hashes:
        for p, claimed in claimed_hashes.items():
            if p not in independent:
                claim_match = False
                claim_why = f"claimed hash for missing content: {p}"
                break
            if claimed and claimed != independent[p]:
                claim_match = False
                claim_why = f"hash mismatch for {p}"
                break
        # Claimed path not in independent set for required paths
        for p in paths:
            if p in claimed_hashes and independent.get(p) and claimed_hashes[p] != independent[p]:
                claim_match = False
                claim_why = f"hash mismatch for {p}"

    # Type-specific byte inspection
    type_ok = True
    type_why = ""
    if primary_language == "pdf" or any((p or "").endswith(".pdf") for p in paths):
        pdf_paths = [p for p in paths if (p or "").endswith(".pdf")] or [
            p for p in contents if (p or "").endswith(".pdf")
        ]
        if not pdf_paths:
            type_ok = False
            type_why = "no pdf path in deliverables"
        else:
            for p in pdf_paths:
                if p not in contents or not pdf_bytes_valid(contents[p]):
                    type_ok = False
                    type_why = f"invalid pdf bytes for {p}"
                    break

    pre = {
        "contract_ok": bool(contract_ok),
        "exact_manifest_ok": bool(exact_manifest_ok),
        "validators_green": bool(validators_green),
        "no_open_hard": int(open_hard or 0) == 0,
        "not_contradictory": not contradictory,
        "receipt_signable": bool(receipt_signable),
        "has_deliverables": bool(paths),
        "has_file_contents": has_contents,
        "hashes_authoritative": hashes_complete and nonempty,
        "claimed_hashes_match": claim_match,
        "type_bytes_ok": type_ok,
    }
    ready = all(pre.values())
    if ready:
        reason = "all closure preconditions met (independent hashes)"
    else:
        failed = [k for k, v in pre.items() if not v]
        extra = []
        if not claim_match and claim_why:
            extra.append(claim_why)
        if not type_ok and type_why:
            extra.append(type_why)
        reason = "not ready: " + ", ".join(failed + extra)
    return ClosureResult(
        ready=ready,
        reason=reason,
        preconditions=pre,
        independent_hashes=independent,
        manifest={
            "paths": list(paths),
            "hashes": independent,  # only independent hashes
            "claimed_hashes_rejected": not claim_match,
        },
        ts=time.time(),
    )


class ClosureProtocol:
    """Stateful closure transaction: freeze, export, block further model turns."""

    def __init__(self) -> None:
        self.closed = False
        self.result: Optional[ClosureResult] = None
        self.model_turns_blocked = 0
        self.writes_blocked = 0
        self.closure_step: Optional[int] = None

    def try_close(
        self,
        evaluation: ClosureResult,
        *,
        checkpoint_id: str = "",
        step: int = 0,
    ) -> ClosureResult:
        if self.closed:
            evaluation.closed = True
            evaluation.blocked_model_turns = self.model_turns_blocked
            evaluation.checkpoint_id = self.result.checkpoint_id if self.result else checkpoint_id
            return evaluation
        if not evaluation.ready:
            self.result = evaluation
            return evaluation
        # Double-check independent hashes present
        if not evaluation.independent_hashes:
            evaluation.ready = False
            evaluation.reason = "not ready: missing independent hashes"
            self.result = evaluation
            return evaluation
        evaluation.closed = True
        evaluation.checkpoint_id = checkpoint_id
        self.closed = True
        self.result = evaluation
        self.closure_step = step
        return evaluation

    def allow_model_turn(self) -> bool:
        if self.closed:
            self.model_turns_blocked += 1
            return False
        return True

    def allow_write(self) -> bool:
        if self.closed:
            self.writes_blocked += 1
            return False
        return True

    def invalidate(self, reason: str = "") -> None:
        self.closed = False
        if self.result:
            self.result.closed = False
            self.result.ready = False
            self.result.reason = f"invalidated: {reason}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "closed": self.closed,
            "closure_step": self.closure_step,
            "model_turns_blocked": self.model_turns_blocked,
            "writes_blocked": self.writes_blocked,
            "result": self.result.to_dict() if self.result else None,
        }
