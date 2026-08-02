# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Last-Known-Green Transaction Store (LGTS).

Green requires artifact-appropriate validators — not mere exit-0 on cat.
Regression includes contract, verifier, and behavioral evidence loss.
Restore is exact-tree: rewrite checkpoint files and delete extras.
"""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lolm.reliability.evidence import hash_tree, meaningful_run_evidence


@dataclass
class GreenCheckpoint:
    checkpoint_id: str
    tree_hash: str
    file_hashes: Dict[str, str]
    file_contents: Dict[str, str]
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
    # True only when artifact-type validators actually ran green
    verified_meaningful: bool = False

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


def _verifier_score(verifier_outputs: Dict[str, Any]) -> float:
    if not verifier_outputs:
        return 0.0
    oks = 0
    n = 0
    for v in verifier_outputs.values():
        if isinstance(v, dict):
            n += 1
            if v.get("ok") is True and not v.get("trivial"):
                oks += 1
    return (oks / n) if n else 0.0


def meaningful_green_evidence(
    *,
    primary_language: str,
    verifier_outputs: Dict[str, Any],
    compile_ok: bool = False,
    run_ok: bool = False,
    run_command: str = "",
) -> Tuple[bool, str]:
    """Reject trivial exit-0 (e.g. cat index.html) as green evidence."""
    vos = verifier_outputs or {}
    if primary_language == "html":
        for key in ("html.render", "html.static_lint", "browser"):
            v = vos.get(key)
            if isinstance(v, dict) and v.get("ok") is True:
                return True, f"{key} green"
        return False, "HTML green requires html.render or html.static_lint working"
    if primary_language == "pdf":
        v = vos.get("pdf.exists") or vos.get("pdf.validate")
        if isinstance(v, dict) and v.get("ok") is True and v.get("valid_magic"):
            return True, "pdf validated"
        return False, "PDF green requires pdf.exists with valid magic bytes"
    # python / default
    syn = vos.get("syntax.python")
    if isinstance(syn, dict) and syn.get("ok") is True:
        # Need a meaningful run or unittest — not cat
        run = vos.get("run") or vos.get("unittest") or vos.get("pytest")
        if isinstance(run, dict) and run.get("ok") is True and not run.get("trivial"):
            return True, "syntax+meaningful run"
        if run_ok and meaningful_run_evidence(run_command, 0 if run_ok else 1):
            return True, "syntax+meaningful run_command"
        if compile_ok and not run_ok and not run:
            # compile-only is a provisional milestone, not full green for delivery
            return False, "syntax alone is not sufficient green for checkpoint"
    if compile_ok and run_ok and meaningful_run_evidence(run_command, 0):
        return True, "compile+meaningful run"
    return False, "insufficient typed verifier evidence for green checkpoint"


def evidence_dominates(
    candidate: Dict[str, Any],
    incumbent: GreenCheckpoint,
    *,
    waiver: bool = False,
) -> Tuple[bool, str]:
    cand_green = int(candidate.get("green_hard") or 0)
    cand_open = int(candidate.get("open_hard") or 0)
    cand_cov = float(candidate.get("contract_coverage") or 0.0)
    cand_verif = candidate.get("verifier_outputs") or {}
    cand_vscore = _verifier_score(cand_verif)
    inc_vscore = _verifier_score(incumbent.verifier_outputs or {})

    if cand_green < incumbent.green_hard and not waiver:
        return False, f"green_hard {cand_green} < incumbent {incumbent.green_hard}"
    if cand_cov + 1e-9 < incumbent.contract_coverage and not waiver:
        return False, f"contract_coverage {cand_cov} < incumbent {incumbent.contract_coverage}"
    if cand_vscore + 1e-9 < inc_vscore and not waiver:
        return False, f"verifier_score {cand_vscore} < incumbent {inc_vscore}"

    for k, v in (incumbent.verifier_outputs or {}).items():
        if isinstance(v, dict) and v.get("ok") is True:
            nv = cand_verif.get(k)
            if isinstance(nv, dict) and nv.get("ok") is False:
                return False, f"verifier regressed: {k}"

    improved = (
        cand_green > incumbent.green_hard
        or cand_open < incumbent.open_hard
        or cand_cov > incumbent.contract_coverage + 1e-9
        or cand_vscore > inc_vscore + 1e-9
        or bool(candidate.get("resolves_hard_criterion"))
    )
    if improved:
        return True, "dominates on evidence frontier"
    if waiver:
        return True, "explicit tradeoff waiver"
    return False, "no objective improvement; model confidence alone never establishes dominance"


class CheckpointStore:
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
        require_meaningful: bool = True,
        primary_language: str = "",
        compile_ok: bool = False,
        run_ok: bool = False,
        run_command: str = "",
    ) -> Optional[GreenCheckpoint]:
        vos = dict(verifier_outputs or {})
        meaningful, mwhy = meaningful_green_evidence(
            primary_language=primary_language,
            verifier_outputs=vos,
            compile_ok=compile_ok,
            run_ok=run_ok,
            run_command=run_command,
        )
        if require_meaningful and not meaningful:
            self.rejected_regressions.append({
                "reason": f"not meaningful green: {mwhy}",
                "step": step,
                "ts": time.time(),
            })
            return None

        file_hashes = hash_tree(file_contents)
        th = _tree_hash(file_hashes)
        vscore = _verifier_score(vos)
        rank = (
            float(green_hard) * 10.0
            + float(contract_coverage)
            + vscore * 5.0
            - float(open_hard)
        )
        cand_meta = {
            "green_hard": green_hard,
            "open_hard": open_hard,
            "contract_coverage": contract_coverage,
            "verifier_outputs": vos,
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
            verifier_outputs=vos,
            environment_fingerprint=environment_fingerprint,
            receipt_parent=receipt_parent,
            step=step,
            rank_score=rank,
            created_ts=time.time(),
            meta=dict(meta or {}, meaningful_why=mwhy),
            verified_meaningful=meaningful,
        )
        self.checkpoints.append(ckpt)
        self.head_id = ckpt.checkpoint_id
        self._persist(ckpt)
        return ckpt

    def force_green(self, **kwargs: Any) -> Optional[GreenCheckpoint]:
        """Record green only if meaningful evidence passes (unless force_unverified)."""
        kwargs.setdefault("force", True)
        kwargs.setdefault("require_meaningful", True)
        return self.snapshot(**kwargs)

    def get(self, checkpoint_id: str) -> Optional[GreenCheckpoint]:
        for c in self.checkpoints:
            if c.checkpoint_id == checkpoint_id:
                return c
        return None

    def best(self) -> Optional[GreenCheckpoint]:
        if not self.checkpoints:
            return None
        verified = [c for c in self.checkpoints if c.verified_meaningful]
        pool = verified or self.checkpoints
        return max(pool, key=lambda c: (c.rank_score, c.created_ts))

    def head(self) -> Optional[GreenCheckpoint]:
        return self.get(self.head_id) if self.head_id else None

    def has_regressed(
        self,
        current_hashes: Dict[str, str],
        *,
        compile_ok: Optional[bool] = None,
        contract_coverage: Optional[float] = None,
        verifier_outputs: Optional[Dict[str, Any]] = None,
        open_hard: Optional[int] = None,
        green_hard: Optional[int] = None,
        extra_files: Optional[Sequence[str]] = None,
        exact_count: Optional[int] = None,
    ) -> Tuple[bool, Optional[GreenCheckpoint], str]:
        """Semantic + contract + compile regression detection."""
        best = self.best()
        if best is None:
            return False, None, "no checkpoint"
        reasons: List[str] = []
        if compile_ok is False:
            reasons.append("compile_failed")
        if contract_coverage is not None and contract_coverage + 1e-9 < best.contract_coverage:
            reasons.append(
                f"contract_coverage {contract_coverage} < {best.contract_coverage}"
            )
        if green_hard is not None and green_hard < best.green_hard:
            reasons.append(f"green_hard {green_hard} < {best.green_hard}")
        if open_hard is not None and open_hard > best.open_hard:
            reasons.append(f"open_hard {open_hard} > {best.open_hard}")
        if verifier_outputs is not None:
            if _verifier_score(verifier_outputs) + 1e-9 < _verifier_score(best.verifier_outputs):
                reasons.append("verifier_score_regressed")
            for k, v in (best.verifier_outputs or {}).items():
                if isinstance(v, dict) and v.get("ok") is True:
                    nv = (verifier_outputs or {}).get(k)
                    if isinstance(nv, dict) and nv.get("ok") is False:
                        reasons.append(f"verifier_regressed:{k}")
        # Lost previously green files
        for p, h in best.file_hashes.items():
            if p not in current_hashes:
                reasons.append(f"missing_file:{p}")
            elif current_hashes[p] != h and compile_ok is False:
                reasons.append(f"content_regressed:{p}")
        # Exact-count pollution
        if exact_count is not None and extra_files:
            extras = [p for p in extra_files if p not in best.file_hashes]
            if extras and len(current_hashes) > exact_count:
                reasons.append(f"extra_files:{extras[:5]}")
        if reasons:
            return True, best, "; ".join(reasons)
        return False, None, ""

    def restore(self, checkpoint_id: Optional[str] = None) -> Optional[GreenCheckpoint]:
        if checkpoint_id:
            return self.get(checkpoint_id)
        return self.best()

    def materialize_to_sandbox(
        self,
        sandbox: Any,
        checkpoint_id: Optional[str] = None,
        *,
        current_paths: Optional[Sequence[str]] = None,
    ) -> Optional[GreenCheckpoint]:
        """Exact tree restore as a typed recovery transaction (not ordinary edit auth)."""
        ckpt = self.restore(checkpoint_id)
        if ckpt is None:
            return None
        from lolm.privileged_mutation import (
            MutationTrustClass,
            build_recovery_transaction,
            read_sandbox_tree,
            tree_manifest,
        )
        before = read_sandbox_tree(sandbox)
        pre_hash = tree_manifest(before)["tree_hash"]
        target = set(ckpt.file_contents.keys())
        # Discover current paths
        paths: List[str] = list(current_paths or [])
        if not paths:
            try:
                paths = list(sandbox.list_files(limit=500))
            except Exception:
                paths = []
        for extra in paths:
            if extra not in target and not extra.startswith("."):
                deleted = False
                if hasattr(sandbox, "delete_file"):
                    try:
                        sandbox.delete_file(extra)
                        deleted = True
                    except Exception:
                        deleted = False
                if not deleted:
                    # Best-effort: empty overwrite is not delete; try pathlib via dir
                    try:
                        root = getattr(sandbox, "dir", None)
                        if root is not None:
                            p = (root / extra).resolve()
                            if root in p.parents or p == root:
                                if p.is_file():
                                    p.unlink()
                                    deleted = True
                    except Exception:
                        pass
                if not deleted:
                    # Last resort: write empty and mark — still imperfect; record
                    try:
                        sandbox.write_file(extra, "", reason="lgts_rollback_clear_extra")
                    except Exception:
                        pass
        for path, content in ckpt.file_contents.items():
            sandbox.write_file(path, content, reason="lgts_rollback")
        after = read_sandbox_tree(sandbox)
        # Expected post tree = checkpoint contents (plus any undeleted leftovers)
        expected = dict(ckpt.file_contents)
        expected_hash = tree_manifest(expected)["tree_hash"]
        restored_hash = tree_manifest(after)["tree_hash"]
        tx = build_recovery_transaction(
            sandbox,
            checkpoint_id=ckpt.checkpoint_id,
            expected_pre_tree_hash=pre_hash,
            before_files=before,
            after_files=after,
            trust_class=MutationTrustClass.RECOVERY_LGTS,
        )
        # exact match against checkpoint body (not residual extras)
        tx.exact_tree_match = restored_hash == expected_hash or all(
            after.get(p) == expected.get(p) for p in expected
        )
        tx.meta["expected_checkpoint_tree_hash"] = expected_hash
        tx.meta["grants_edit_authorization"] = False
        # Attach for callers / receipts without changing return type
        try:
            setattr(ckpt, "recovery_transaction", tx.to_dict())
        except Exception:
            pass
        self._last_recovery_transaction = tx.to_dict()
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
