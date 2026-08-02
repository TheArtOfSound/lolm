# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Queued campaign execution with signed aggregate receipts."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence


class CaseStatus(str, Enum):
    QUEUED = "queued"
    ADMITTED = "admitted"
    EXECUTING = "executing"
    PASSED = "passed"
    MODEL_FAILED = "model_failed"
    CONTRACT_FAILED = "contract_failed"
    INFRASTRUCTURE_FAILED = "infrastructure_failed"
    CANCELED = "canceled"
    INVALID = "invalid"
    # Explicitly NOT used for capacity: capacity → stays QUEUED, never model_failed
    NOT_ADMITTED = "not_admitted"  # only for auth/manifest rejection, not quota


@dataclass
class CaseRecord:
    case_id: str
    status: str = CaseStatus.QUEUED.value
    seed: int = 0
    task: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    admitted_ts: float = 0.0
    finished_ts: float = 0.0
    receipt_sha: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CampaignManifest:
    campaign_id: str
    package_version: str
    server_version: str
    reasoner_profile: str
    controller_version: str
    verifier_version: str
    concurrency: int = 4
    seeds: List[int] = field(default_factory=list)
    case_ids: List[str] = field(default_factory=list)
    auth_token_hash: str = ""
    created_ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def pin_hash(self) -> str:
        raw = json.dumps({
            "package_version": self.package_version,
            "server_version": self.server_version,
            "reasoner_profile": self.reasoner_profile,
            "controller_version": self.controller_version,
            "verifier_version": self.verifier_version,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class CampaignQueue:
    """In-process evaluation queue — never 429-rejects admitted campaigns.

    Capacity limits delay execution (queue) rather than mislabel model failure.
    """

    def __init__(self, manifest: CampaignManifest) -> None:
        self.manifest = manifest
        self.cases: Dict[str, CaseRecord] = {}
        self._active = 0
        self._order: List[str] = []

    def submit_cases(
        self,
        tasks: Sequence[Dict[str, Any]],
        *,
        authenticated: bool = True,
    ) -> List[CaseRecord]:
        if not authenticated:
            # Auth failure → not_admitted (not model_failed)
            out = []
            for i, t in enumerate(tasks):
                cid = t.get("case_id") or f"case_{i}"
                rec = CaseRecord(
                    case_id=cid,
                    status=CaseStatus.NOT_ADMITTED.value,
                    task=t.get("task") or "",
                    error="authentication required for evaluation plane",
                )
                self.cases[cid] = rec
                out.append(rec)
            return out

        out = []
        for i, t in enumerate(tasks):
            cid = t.get("case_id") or f"case_{uuid.uuid4().hex[:10]}"
            seed = int(t.get("seed") if t.get("seed") is not None
                       else (self.manifest.seeds[i] if i < len(self.manifest.seeds) else i))
            rec = CaseRecord(
                case_id=cid,
                status=CaseStatus.QUEUED.value,
                seed=seed,
                task=t.get("task") or "",
            )
            self.cases[cid] = rec
            self._order.append(cid)
            if cid not in self.manifest.case_ids:
                self.manifest.case_ids.append(cid)
            out.append(rec)
        return out

    def admit_next(self) -> Optional[CaseRecord]:
        """Admit up to concurrency leases — queue, never reject for capacity."""
        if self._active >= max(1, self.manifest.concurrency):
            return None  # wait; still QUEUED, not NOT_ADMITTED
        for cid in self._order:
            rec = self.cases[cid]
            if rec.status == CaseStatus.QUEUED.value:
                rec.status = CaseStatus.ADMITTED.value
                rec.admitted_ts = time.time()
                self._active += 1
                return rec
        return None

    def mark_executing(self, case_id: str) -> None:
        rec = self.cases[case_id]
        rec.status = CaseStatus.EXECUTING.value

    def complete(
        self,
        case_id: str,
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: str = "",
        receipt_sha: str = "",
    ) -> CaseRecord:
        rec = self.cases[case_id]
        # Guard: never convert capacity into model_failed
        if status == CaseStatus.NOT_ADMITTED.value and rec.status in (
            CaseStatus.QUEUED.value, CaseStatus.ADMITTED.value, CaseStatus.EXECUTING.value
        ):
            status = CaseStatus.INFRASTRUCTURE_FAILED.value
            error = error or "internal: capacity must not become not_admitted after queue"
        rec.status = status
        rec.result = dict(result or {})
        rec.error = error
        rec.receipt_sha = receipt_sha
        rec.finished_ts = time.time()
        if self._active > 0:
            self._active -= 1
        return rec

    def run_all(
        self,
        executor: Callable[[CaseRecord], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Drain queue with concurrency leases."""
        pending = True
        while pending:
            pending = False
            while True:
                rec = self.admit_next()
                if rec is None:
                    break
                pending = True
                self.mark_executing(rec.case_id)
                try:
                    out = executor(rec) or {}
                    status = out.get("status") or CaseStatus.PASSED.value
                    # Sanitize mislabels
                    if status in ("rate_limited", "quota", "429"):
                        status = CaseStatus.INFRASTRUCTURE_FAILED.value
                    self.complete(
                        rec.case_id,
                        status=status,
                        result=out.get("result") or out,
                        error=out.get("error") or "",
                        receipt_sha=out.get("receipt_sha") or "",
                    )
                except Exception as exc:
                    self.complete(
                        rec.case_id,
                        status=CaseStatus.INFRASTRUCTURE_FAILED.value,
                        error=str(exc)[:300],
                    )
            # If all remaining are queued but concurrency full, we'd need async;
            # for sync executor we always free slots in complete().
            if any(c.status == CaseStatus.QUEUED.value for c in self.cases.values()):
                if self._active == 0:
                    # should have admitted — break to avoid spin
                    break
                pending = True
        return self.summary()

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for c in self.cases.values():
            counts[c.status] = counts.get(c.status, 0) + 1
        return {
            "campaign_id": self.manifest.campaign_id,
            "pin_hash": self.manifest.pin_hash(),
            "total": len(self.cases),
            "counts": counts,
            "cases": [c.to_dict() for c in self.cases.values()],
        }


def sign_campaign_receipt(summary: Dict[str, Any], *, secret: str = "") -> Dict[str, Any]:
    """Signed aggregate campaign receipt (HMAC-like sha over payload + secret)."""
    payload = {
        "campaign_id": summary.get("campaign_id"),
        "pin_hash": summary.get("pin_hash"),
        "total": summary.get("total"),
        "counts": summary.get("counts"),
        "case_ids": [c.get("case_id") for c in (summary.get("cases") or [])],
        "case_status": {c.get("case_id"): c.get("status") for c in (summary.get("cases") or [])},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256((raw + "|" + secret).encode()).hexdigest()
    return {
        "schema": "lolm.campaign_receipt.v1",
        "payload": payload,
        "receipt_sha256": digest,
        "signed_at": time.time(),
    }
