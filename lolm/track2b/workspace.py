# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Final workspace evidence for Track 2B SSE runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes((text or "").encode("utf-8", errors="replace"))


def tree_hash(files: Dict[str, str]) -> str:
    """Exact tree hash: sorted path → content sha256, then outer sha256."""
    hashes = {k: _sha256_text(v) for k, v in sorted((files or {}).items())}
    payload = json.dumps(hashes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def trees_equal(a: Dict[str, str], b: Dict[str, str]) -> bool:
    return tree_hash(a) == tree_hash(b)


def build_final_workspace(
    files: Dict[str, str],
    *,
    binary_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    run_id: str = "",
    max_text_bytes: int = 400_000,
) -> Dict[str, Any]:
    """Build a final_workspace event payload from a path→text map."""
    paths: List[str] = []
    contents: Dict[str, str] = {}
    file_sha256: Dict[str, str] = {}
    omitted: List[Dict[str, Any]] = []
    binary_meta = binary_meta or {}

    for path, body in sorted((files or {}).items()):
        paths.append(path)
        raw = (body or "").encode("utf-8", errors="replace")
        file_sha256[path] = _sha256_bytes(raw)
        if path in binary_meta:
            meta = {"path": path, **binary_meta[path]}
            omitted.append(meta)
            if binary_meta[path].get("sha256"):
                file_sha256[path] = binary_meta[path]["sha256"]
            continue
        if len(raw) > max_text_bytes:
            omitted.append({
                "path": path,
                "reason": "too_large",
                "size": len(raw),
                "sha256": file_sha256[path],
            })
            continue
        # Reject NUL as binary
        if "\x00" in (body or ""):
            omitted.append({
                "path": path,
                "reason": "binary_nul",
                "size": len(raw),
                "sha256": file_sha256[path],
            })
            continue
        contents[path] = body if isinstance(body, str) else body.decode("utf-8", "replace")

    # Binary-only paths declared solely via binary_meta
    for path, meta in sorted((binary_meta or {}).items()):
        if path not in paths:
            paths.append(path)
            omitted.append({"path": path, **meta})
            if meta.get("sha256"):
                file_sha256[path] = meta["sha256"]

    th = tree_hash(contents)

    return {
        "schema": "lolm.final_workspace.v1",
        "run_id": run_id,
        "paths": paths,
        "files": contents,
        "file_sha256": file_sha256,
        "tree_hash": th,
        "omitted": omitted,
        "complete": len(omitted) == 0 and set(paths) == set(contents),
    }


def reconstruct_tree(final_workspace: Dict[str, Any]) -> Tuple[Dict[str, str], str, List[str]]:
    """Reconstruct text tree from final_workspace event. Returns (tree, hash, errors)."""
    errors: List[str] = []
    if not final_workspace:
        return {}, "", ["final_workspace_absent"]
    files = dict(final_workspace.get("files") or {})
    declared = final_workspace.get("tree_hash") or ""
    computed = tree_hash(files)
    if declared and declared != computed:
        errors.append("final_workspace_tree_hash_mismatch")
    for path, sha in (final_workspace.get("file_sha256") or {}).items():
        if path in files and _sha256_text(files[path]) != sha:
            errors.append(f"file_sha_mismatch:{path}")
    return files, computed, errors
