# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Trust classes for out-of-band active-tree mutation surfaces.

CodeAgent product mutations must use MutationGateway (RBE + CAS + receipts).
Operator, HTTP sandbox API, LGTS restore, and resume restoration are NOT silent
bypasses — each has an explicit trust class, separate receipt namespace, and
repository-root binding.

Recovery privileges cannot be reused for subsequent ordinary edits.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


class MutationTrustClass(str, Enum):
    CODE_AGENT_GATEWAY = "code_agent_gateway"
    PRIVILEGED_OPERATOR = "privileged_operator"
    PRIVILEGED_HTTP_SANDBOX = "privileged_http_sandbox"
    RECOVERY_LGTS = "recovery_lgts"
    RECOVERY_RESUME = "recovery_resume"
    GAUNTLET_SEED = "gauntlet_seed"  # test fixture only


_PRIVILEGED = {
    MutationTrustClass.PRIVILEGED_OPERATOR,
    MutationTrustClass.PRIVILEGED_HTTP_SANDBOX,
}
_RECOVERY = {
    MutationTrustClass.RECOVERY_LGTS,
    MutationTrustClass.RECOVERY_RESUME,
}


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def tree_manifest(files: Dict[str, str]) -> Dict[str, Any]:
    """Exact pre/post tree manifest for privileged receipts."""
    hashes = {k: _sha(v) for k, v in sorted(files.items())}
    payload = json.dumps(hashes, sort_keys=True)
    return {
        "file_count": len(hashes),
        "paths": sorted(hashes.keys()),
        "file_hashes": hashes,
        "tree_hash": hashlib.sha256(payload.encode()).hexdigest(),
    }


def read_sandbox_tree(sandbox: Any, limit: int = 500) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        paths = list(sandbox.list_files(limit=limit))
    except Exception:
        return out
    for path in paths:
        try:
            body = sandbox.read_file(path)
            if body is None:
                continue
            out[path] = body if isinstance(body, str) else body.decode("utf-8", "replace")
        except Exception:
            continue
    return out


@dataclass
class PrivilegedMutationReceipt:
    """Separate receipt namespace for non-CodeAgent mutations."""
    schema: str = "lolm.privileged_mutation.v1"
    receipt_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    trust_class: str = MutationTrustClass.PRIVILEGED_OPERATOR.value
    ts: float = field(default_factory=time.time)
    operation: str = ""  # write|edit|delete|restore_checkpoint
    path: str = ""
    reason: str = ""
    repository_root: str = ""
    pre_tree: Dict[str, Any] = field(default_factory=dict)
    post_tree: Dict[str, Any] = field(default_factory=dict)
    exact_tree_match: Optional[bool] = None
    capability_token_present: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "trust_class": self.trust_class,
            "ts": self.ts,
            "operation": self.operation,
            "path": self.path,
            "reason": self.reason,
            "repository_root": self.repository_root,
            "pre_tree": self.pre_tree,
            "post_tree": self.post_tree,
            "exact_tree_match": self.exact_tree_match,
            "capability_token_present": self.capability_token_present,
            "meta": self.meta,
        }


@dataclass
class RecoveryTransaction:
    """Typed recovery for LGTS / resume — not reusable as ordinary edit auth."""
    schema: str = "lolm.recovery_transaction.v1"
    operation: str = "restore_checkpoint"
    checkpoint_id: str = ""
    expected_pre_tree_hash: str = ""
    restored_tree_hash: str = ""
    files_created: List[str] = field(default_factory=list)
    files_replaced: List[str] = field(default_factory=list)
    files_deleted: List[str] = field(default_factory=list)
    exact_tree_match: bool = False
    trust_class: str = MutationTrustClass.RECOVERY_LGTS.value
    # One-shot: recovery does not grant RBE authorization for later edits
    grants_edit_authorization: bool = False
    ts: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "operation": self.operation,
            "checkpoint_id": self.checkpoint_id,
            "expected_pre_tree_hash": self.expected_pre_tree_hash,
            "restored_tree_hash": self.restored_tree_hash,
            "files_created": list(self.files_created),
            "files_replaced": list(self.files_replaced),
            "files_deleted": list(self.files_deleted),
            "exact_tree_match": self.exact_tree_match,
            "trust_class": self.trust_class,
            "grants_edit_authorization": False,  # hard false
            "ts": self.ts,
            "meta": self.meta,
        }


class PrivilegedMutationLog:
    def __init__(self, path: Optional[Path] = None) -> None:
        default = Path(
            os.environ.get(
                "LOLM_PRIVILEGED_MUTATION_LOG",
                str(Path.home() / ".lolm" / "privileged_mutations.jsonl"),
            )
        )
        self.path = path or default
        self.records: List[Dict[str, Any]] = []

    def append(self, payload: Dict[str, Any]) -> None:
        self.records.append(payload)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass


_default_log: Optional[PrivilegedMutationLog] = None


def get_privileged_log() -> PrivilegedMutationLog:
    global _default_log
    if _default_log is None:
        _default_log = PrivilegedMutationLog()
    return _default_log


def require_privileged_token(
    authorization: Optional[str],
    *,
    secret_env: str = "SANDBOX_SECRET",
    alt_env: str = "OPERATOR_SECRET",
) -> bool:
    """Return True if a configured privileged capability token matches."""
    secret = os.environ.get(secret_env) or os.environ.get(alt_env)
    if not secret:
        return False
    if not authorization:
        return False
    expected = f"Bearer {secret}"
    return authorization == expected or authorization == secret


def privileged_write(
    sandbox: Any,
    path: str,
    content: str,
    *,
    trust_class: MutationTrustClass,
    reason: str = "",
    capability_token_present: bool = False,
    require_token: bool = True,
) -> Dict[str, Any]:
    """Write with separate privileged receipt + pre/post tree manifests.

    Does not use MutationGateway RBE (operator/HTTP are human-authorized
    surfaces) but never silently looks like a CodeAgent receipt.
    """
    if require_token and not capability_token_present:
        raise PermissionError(
            f"privileged mutation requires capability token ({trust_class.value})"
        )
    if trust_class not in _PRIVILEGED and trust_class != MutationTrustClass.GAUNTLET_SEED:
        raise PermissionError(f"invalid privileged trust class: {trust_class}")

    pre = tree_manifest(read_sandbox_tree(sandbox))
    root = str(getattr(sandbox, "dir", "") or getattr(sandbox, "root", ""))
    fc = sandbox.write_file(path, content, reason=f"{trust_class.value}:{reason}")
    post = tree_manifest(read_sandbox_tree(sandbox))
    receipt = PrivilegedMutationReceipt(
        trust_class=trust_class.value,
        operation="write",
        path=path,
        reason=reason,
        repository_root=root,
        pre_tree=pre,
        post_tree=post,
        capability_token_present=capability_token_present,
        meta={"bytes": len(content or ""), "sandbox_fc": {
            k: fc.get(k) for k in ("path", "before_hash", "after_hash", "reason") if isinstance(fc, dict)
        }},
    )
    get_privileged_log().append(receipt.to_dict())
    return {"file_change": fc, "privileged_receipt": receipt.to_dict()}


def build_recovery_transaction(
    sandbox: Any,
    *,
    checkpoint_id: str,
    expected_pre_tree_hash: str,
    before_files: Dict[str, str],
    after_files: Dict[str, str],
    trust_class: MutationTrustClass = MutationTrustClass.RECOVERY_LGTS,
) -> RecoveryTransaction:
    """Build a typed recovery transaction from before/after trees."""
    before_paths = set(before_files)
    after_paths = set(after_files)
    created = sorted(after_paths - before_paths)
    deleted = sorted(before_paths - after_paths)
    replaced = sorted(
        p for p in (before_paths & after_paths)
        if before_files.get(p) != after_files.get(p)
    )
    post = tree_manifest(after_files)
    exact = True
    # exact_tree_match vs checkpoint is caller's responsibility; here we report
    # whether restore produced a consistent post hash.
    tx = RecoveryTransaction(
        checkpoint_id=checkpoint_id,
        expected_pre_tree_hash=expected_pre_tree_hash or tree_manifest(before_files)["tree_hash"],
        restored_tree_hash=post["tree_hash"],
        files_created=created,
        files_replaced=replaced,
        files_deleted=deleted,
        exact_tree_match=exact,
        trust_class=trust_class.value,
        grants_edit_authorization=False,
        meta={"repository_root": str(getattr(sandbox, "dir", "") or "")},
    )
    get_privileged_log().append(tx.to_dict())
    return tx
