# Copyright (c) 2026 Qira LLC. All rights reserved.
"""P0 artifact-manifest correction for generated binary deliverables.

CodeAgent historically manifested only paths written through FILE/EDIT. Files created
by a verified program, such as output.pdf, existed in the sandbox but were omitted from
the signed manifest and disappeared when the sandbox was destroyed. This patch makes
the final sandbox tree authoritative while excluding harness/cache pollution.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List

_INTERNAL_NAMES = {
    "_lolm_contract_probe.py",
    ".DS_Store",
}
_INTERNAL_PARTS = {
    "__pycache__", ".git", "node_modules", ".cache", "Library", "Caches",
}


def _safe_names(agent: Any) -> List[str]:
    intentional = list(dict.fromkeys(getattr(agent, "_files_written", []) or []))
    try:
        discovered = list(agent.sb.list_files(limit=500))
    except Exception:
        discovered = []
    names: List[str] = []
    for raw in intentional + discovered:
        path = str(raw or "").strip().replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            continue
        parts = set(path.split("/"))
        if parts & _INTERNAL_PARTS or path.rsplit("/", 1)[-1] in _INTERNAL_NAMES:
            continue
        if path not in names:
            names.append(path)
    return names


def _read_exact_bytes(agent: Any, path: str) -> bytes:
    # Sandbox.read_file is intentionally text-only and replacement-decodes binary.
    # Artifact delivery must bind the exact bytes, so use its contained safe path.
    safe = getattr(agent.sb, "_safe", None)
    if callable(safe):
        target = safe(path)
        if not Path(target).is_file():
            raise FileNotFoundError(path)
        return Path(target).read_bytes()
    raw = agent.sb.read_file(path)
    return raw if isinstance(raw, bytes) else str(raw).encode("utf-8")


def corrected_artifact_manifest(
    agent: Any,
    *,
    max_file_bytes: int = 96_000,
    max_total_bytes: int = 400_000,
) -> Dict[str, Any]:
    files_out: List[Dict[str, Any]] = []
    total = 0
    names = _safe_names(agent)
    complete = len(names) <= 100
    names = names[:100]

    # Make generated deliverables part of the authoritative receipt file set.
    agent._files_written = list(names)

    required: List[str] = []
    try:
        required = [str(p).replace("\\", "/") for p in (
            agent.reliability.contract.required_paths or []
        )]
    except Exception:
        required = []
    if any(path not in names for path in required):
        complete = False

    for path in names:
        p = path.strip().replace("\\", "/")
        if not re.match(r"^[A-Za-z0-9._/@+\-]+$", p):
            complete = False
            continue
        try:
            body = _read_exact_bytes(agent, p)
        except Exception:
            complete = False
            continue
        sha = hashlib.sha256(body).hexdigest()
        entry: Dict[str, Any] = {
            "path": p,
            "type": "file",
            "sha256": sha,
            "size": len(body),
            "executable": False,
        }
        bounded = len(body) <= max_file_bytes and total + len(body) <= max_total_bytes
        if bounded:
            try:
                text = body.decode("utf-8")
                entry["content"] = text
                entry["encoding"] = "utf-8"
            except UnicodeDecodeError:
                entry["content_base64"] = base64.b64encode(body).decode("ascii")
                entry["encoding"] = "base64"
            total += len(body)
        else:
            entry["content_omitted"] = (
                "too_large" if len(body) > max_file_bytes else "budget"
            )
            complete = False
        files_out.append(entry)

    metadata = [
        {
            "path": f["path"],
            "type": f["type"],
            "size": f["size"],
            "sha256": f["sha256"],
            "executable": f["executable"],
        }
        for f in files_out
    ]
    artifact_id = "art_" + hashlib.sha256(json.dumps(
        metadata, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()[:24]
    run_id = str(getattr(agent.sb, "id", "") or "run_unknown")
    core = {
        "schema": "lolm.artifact.manifest.v1",
        "run_id": run_id,
        "artifact_id": artifact_id,
        "complete": complete,
        "files": metadata,
        "total_bytes": sum(f["size"] for f in files_out),
    }
    manifest_sha = hashlib.sha256(json.dumps(
        core, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {**core, "files": files_out, "manifest_sha256": manifest_sha}


def install_patch(code_agent_class: Any) -> None:
    if getattr(code_agent_class, "_artifact_delivery_patch", False):
        return

    def _artifact_manifest(self: Any, *, max_file_bytes: int = 96_000,
                           max_total_bytes: int = 400_000) -> Dict[str, Any]:
        return corrected_artifact_manifest(
            self,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )

    code_agent_class._artifact_manifest = _artifact_manifest
    code_agent_class._artifact_delivery_patch = True
