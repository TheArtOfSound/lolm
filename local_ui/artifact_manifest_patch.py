# Copyright (c) 2026 Qira LLC. All rights reserved.
"""P0 artifact delivery and server-side credential-safety corrections.

CodeAgent historically manifested only paths written through FILE/EDIT. Files created
by a verified program, such as output.pdf, existed in the sandbox but were omitted from
the signed manifest and disappeared when the sandbox was destroyed. This patch makes
the final sandbox tree authoritative while excluding harness/cache pollution.

The same runtime layer refuses requests to fabricate official attendance, enrollment,
employment, or similar credentials before any model or tool execution. Clearly labeled
unofficial self-attestations and assembly of authentic evidence remain allowed.
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


def official_credential_fabrication(task: str) -> bool:
    text = str(task or "").lower()
    if re.search(
        r"\b(unofficial|self[- ]?attestation|personal statement|clearly labeled draft)\b",
        text,
    ):
        return False
    proof = bool(re.search(
        r"\b(proof|prove|proving|verification|verify|certificate|official letter|transcript)\b",
        text,
    ))
    status = bool(re.search(
        r"\b(attend|attendance|enroll|enrollment|student|graduate|graduated|employed|employment)\b",
        text,
    ))
    institution = bool(re.search(
        r"\b(asu|university|college|school|employer|company|government|bank)\b",
        text,
    ))
    return proof and status and institution


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

    original_run = code_agent_class.run

    def _artifact_manifest(self: Any, *, max_file_bytes: int = 96_000,
                           max_total_bytes: int = 400_000) -> Dict[str, Any]:
        return corrected_artifact_manifest(
            self,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )

    def _run(self: Any, task: str):
        if official_credential_fabrication(task):
            run_id = str(getattr(getattr(self, "sb", None), "id", "") or "refused")
            identity: Dict[str, Any] = {}
            try:
                identity = dict(self._deployment_identity() or {})
            except Exception:
                identity = {}
            yield {"event": "code_start", "data": {
                "task": task,
                "sandbox": run_id,
                **identity,
            }}
            message = (
                "LOLM cannot fabricate official proof of attendance, enrollment, "
                "employment, or another credential. It can create a clearly labeled "
                "unofficial self-attestation, draft a request for genuine verification, "
                "or assemble authentic documents supplied by the user."
            )
            yield {"event": "agent_note", "data": {
                "text": "request refused before model or tool execution",
                "safety_code": "OFFICIAL_CREDENTIAL_FABRICATION",
            }}
            yield {"event": "error", "data": {
                "error": message,
                "code": "OFFICIAL_CREDENTIAL_FABRICATION",
                "retryable": False,
            }}
            yield {"event": "code_done", "data": {
                "run_id": run_id,
                "ok": False,
                "verdict": "refused",
                "summary": message,
                "files": [],
                "ran": False,
                **identity,
            }}
            return
        yield from original_run(self, task)

    code_agent_class._artifact_manifest = _artifact_manifest
    code_agent_class.run = _run
    code_agent_class._artifact_delivery_patch = True
    code_agent_class._credential_safety_patch = True
