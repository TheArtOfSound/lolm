# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Last-Known-Green Transaction Store (LGTS).

Treat verified artifacts like database commits. Snapshot tree hash, file hashes,
contract coverage, verifier outputs, environment fingerprint, and receipt parent.
On budget exhaustion, crash, or regression, deliver the best green checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class GreenCheckpoint:
    checkpoint_id: str
    tree_hash: str
    file_hashes: Dict[str, str]
    file_contents: Dict[str, str]  # path -> text (immutable snapshot)
    contract_coverage: float
    green_hard: int
    open_hard: int
    verifier_outputs: Dict[str, Any] = field(default_factory=dict)
    environment_fingerprint: str = ""
    receipt_parent: str = ""
    step: int = 0
    rank_score: float = 0.0
    created_ts: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_contents: bool = True) -> Dict[str, Any]:
        d = asdict(self)
        if not include_contents:
            d["file_contents"] = {k: f"<omitted len={len(v)}>" for k, v in self.file_contents.items()}
        return d


def _tree_hash(file_hashes: Dict[str, str]) -> str:
    payload = json.dumps(file_hashes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _cid(tree_hash: str, step: int) -> str:
    return "ckpt_" + hashlib.sha256(f"{tree_hash}:{step}".encode()).hexdigest()[:16]


def evidence_dominates(
    candidate: Dict[str, Any],
    incumbent: GreenCheckpoint,
    *,
    waiver: bool = False,
) -> Tuple[bool, str]:
    """Candidate B may replace A only when hard clauses stay satisfied and
    B improves at least one objective (or explicit tradeoff/waiver)."""
    cand_green = int(candidate.get("green_hard") or 0)
    cand_open = int(candidate.get("open_hard") or 0)
    cand_cov = float(candidate.get("contract_coverage") or 0.0)
    cand_verif = candidate.get("verifier_outputs") or {}

    # No hard-clause regression
    if cand_green < incumbent.green_hard and not waiver:
        return False, f"green_hard {cand_green} < incumbent {incumbent.green_hard}"
    # Verifier regression: any key that was ok and is now fail
    for k, v in (incumbent.verifier_outputs or {}).items():
        if isinstance(v, dict) and v.get("ok") is True:
            nv = cand_verif.get(k)
            if isinstance(nv, dict) and nv.get("ok") is False:
                return False, f"verifier regressed: {k}"

    improved = (
        cand_green > incumbent.green_hard
        or cand_open < incumbent.open_hard
        or cand_cov > incumbent.contract_coverage + 1e-9
        or bool(candidate.get("resolves_hard_criterion"))
    )
    if improved:
        return True, "dominates on evidence frontier"
    if waiver:
        return True, "explicit tradeoff waiver"
    return False, "no objective improvement; model confidence alone never establishes dominance"


class CheckpointStore:
    """Immutable green snapshots with rollback."""

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        self.checkpoints: List[GreenCheckpoint] = []
        self.head_id: Optional[str] = None
        self.rejected_regressions: List[Dict[str, Any]] = []
        self.persist_dir = Path(persist_dir) if persist_dir else None
        if self.persist_dir:
            self.persist_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(
        self,
        file_contents: Dict[str, str],
        *,
        contract_coverage: float = 0.0,
        green_hard: int = 0,
        open_hard: int = 0,
        verifier_outputs: Optional[Dict[str, Any]] = None,
        environment_fingerprint: str = "",
        receipt_parent: str = "",
        step: int = 0,
        meta: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Optional[GreenCheckpoint]:
        """Create a green checkpoint if evidence dominates head (or force first)."""
        file_hashes = {
            p: hashlib.sha256(c.encode("utf-8", errors="replace")).hexdigest()
            for p, c in sorted(file_contents.items())
        }
        th = _tree_hash(file_hashes)
        rank = float(green_hard) * 10.0 + float(contract_coverage) - float(open_hard)
        cand_meta = {
            "green_hard": green_hard,
            "open_hard": open_hard,
            "contract_coverage": contract_coverage,
            "verifier_outputs": verifier_outputs or {},
        }
        if self.head_id and not force:
            head = self.get(self.head_id)
            if head:
                ok, why = evidence_dominates(cand_meta, head)
                if not ok:
                    self.rejected_regressions.append({
                        "reason": why,
                        "tree_hash": th,
                        "step": step,
                        "ts": time.time(),
                    })
                    return None

        ckpt = GreenCheckpoint(
            checkpoint_id=_cid(th, step),
            tree_hash=th,
            file_hashes=file_hashes,
            file_contents=deepcopy(file_contents),
            contract_coverage=contract_coverage,
            green_hard=green_hard,
            open_hard=open_hard,
            verifier_outputs=dict(verifier_outputs or {}),
            environment_fingerprint=environment_fingerprint,
            receipt_parent=receipt_parent,
            step=step,
            rank_score=rank,
            created_ts=time.time(),
            meta=dict(meta or {}),
        )
        self.checkpoints.append(ckpt)
        self.head_id = ckpt.checkpoint_id
        self._persist(ckpt)
        return ckpt

    def force_green(self, **kwargs: Any) -> GreenCheckpoint:
        """Record a known-green milestone (syntax+run or contract gate)."""
        kwargs["force"] = True
        ckpt = self.snapshot(**kwargs)
        assert ckpt is not None
        return ckpt

    def get(self, checkpoint_id: str) -> Optional[GreenCheckpoint]:
        for c in self.checkpoints:
            if c.checkpoint_id == checkpoint_id:
                return c
        return None

    def best(self) -> Optional[GreenCheckpoint]:
        if not self.checkpoints:
            return None
        return max(self.checkpoints, key=lambda c: (c.rank_score, c.created_ts))

    def head(self) -> Optional[GreenCheckpoint]:
        return self.get(self.head_id) if self.head_id else None

    def has_regressed(
        self,
        current_hashes: Dict[str, str],
        *,
        compile_ok: Optional[bool] = None,
    ) -> Tuple[bool, Optional[GreenCheckpoint]]:
        """True if we had a green checkpoint and current tree is worse."""
        best = self.best()
        if best is None:
            return False, None
        if compile_ok is False:
            return True, best
        # If any previously green file is missing or hash-changed to something
        # that failed validation, treat as regression when compile_ok False only
        # for syntax; for hash-only we need external signal.
        cur_tree = _tree_hash(current_hashes)
        if cur_tree != best.tree_hash and compile_ok is False:
            return True, best
        return False, None

    def restore(self, checkpoint_id: Optional[str] = None) -> Optional[GreenCheckpoint]:
        """Return the checkpoint to materialize (does not write to disk itself)."""
        if checkpoint_id:
            return self.get(checkpoint_id)
        return self.best()

    def materialize_to_sandbox(
        self,
        sandbox: Any,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[GreenCheckpoint]:
        """Write checkpoint file contents into a sandbox (write_file API)."""
        ckpt = self.restore(checkpoint_id)
        if ckpt is None:
            return None
        for path, content in ckpt.file_contents.items():
            sandbox.write_file(path, content, reason="lgts_rollback")
        return ckpt

    def _persist(self, ckpt: GreenCheckpoint) -> None:
        if not self.persist_dir:
            return
        path = self.persist_dir / f"{ckpt.checkpoint_id}.json"
        path.write_text(
            json.dumps(ckpt.to_dict(include_contents=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "head_id": self.head_id,
            "checkpoints": [c.to_dict(include_contents=False) for c in self.checkpoints],
            "rejected_regressions": list(self.rejected_regressions[-50:]),
        }
