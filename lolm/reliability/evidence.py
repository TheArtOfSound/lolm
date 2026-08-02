# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Evidence helpers: exit codes, hashes, verifier schema normalization.

Independent of caller assertions — used by closure, LGTS, and the live loop.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

# Commands that prove nothing about artifact correctness (read/list only).
_TRIVIAL_CMD = re.compile(
    r"^\s*(cat|head|tail|less|more|wc|ls|echo|true|file|stat|strings)\b",
    re.I,
)
_PDF_MAGIC = b"%PDF"


def coerce_exit_code(result: Optional[Mapping[str, Any]]) -> int:
    """Preserve exit code 0. Never use ``x or 1`` on numeric codes.

    Missing / None → 1 (failed). Explicit 0 → 0.
    """
    if result is None:
        return 1
    if "exit_code" in result:
        v = result["exit_code"]
    elif "exit" in result:
        v = result["exit"]
    else:
        return 1
    if v is None:
        return 1
    try:
        return int(v)
    except (TypeError, ValueError):
        return 1


def content_sha256(content: Union[str, bytes, bytearray]) -> str:
    if isinstance(content, str):
        body = content.encode("utf-8", errors="replace")
    else:
        body = bytes(content)
    return hashlib.sha256(body).hexdigest()


def hash_tree(file_contents: Mapping[str, Union[str, bytes]]) -> Dict[str, str]:
    """Independently hash actual artifact bytes (authoritative)."""
    return {p: content_sha256(c) for p, c in sorted(file_contents.items())}


def pdf_bytes_valid(content: Union[str, bytes, bytearray]) -> bool:
    """Minimal authoritative PDF evidence: magic + non-trivial size."""
    if isinstance(content, str):
        raw = content.encode("latin-1", errors="replace")
    else:
        raw = bytes(content)
    if len(raw) < 64:
        return False
    return raw[:4] == _PDF_MAGIC or raw.lstrip()[:4] == _PDF_MAGIC


def is_trivial_command(command: str) -> bool:
    """True if the command cannot establish artifact-correctness evidence."""
    cmd = (command or "").strip()
    if not cmd:
        return True
    if _TRIVIAL_CMD.match(cmd):
        return True
    # pure python -c 'print(...)' without real module under test is weak —
    # still allowed as run evidence if exit 0 for simple scripts; not for green HTML.
    return False


def html_verdict_ok(verdict: Optional[Mapping[str, Any]]) -> Tuple[bool, str]:
    """Normalize browser / static-lint verifier schemas.

    Existing code_routes returns: working, renders, animates, responds.
    Some paths may use ok/passed. Accept either family.
    """
    if not verdict:
        return False, "no verdict"
    # Preferred schema (code_routes / Chromium / static lint)
    if "working" in verdict:
        if verdict.get("working") is True:
            return True, "working=true"
        reasons = verdict.get("reasons") or []
        return False, "working=false: " + "; ".join(str(r) for r in reasons[:3])
    # Alternate schemas
    if verdict.get("ok") is True or verdict.get("passed") is True:
        return True, "ok/passed"
    if verdict.get("ok") is False or verdict.get("passed") is False:
        return False, "ok/passed=false"
    # Partial positive: renders without hard fail flags
    if verdict.get("renders") is True and not verdict.get("unavailable"):
        if verdict.get("console_errors"):
            return False, "renders but console_errors present"
        return True, "renders=true"
    return False, "unrecognized verifier schema"


def normalize_verifier_output(
    name: str,
    verdict: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Canonical verifier evidence record for checkpoints and closure."""
    if name in ("html.render", "html.static_lint", "browser"):
        ok, why = html_verdict_ok(verdict)
        return {
            "ok": ok,
            "name": name,
            "why": why,
            "working": (verdict or {}).get("working"),
            "renders": (verdict or {}).get("renders"),
            "animates": (verdict or {}).get("animates"),
            "responds": (verdict or {}).get("responds"),
            "raw_keys": list((verdict or {}).keys())[:20],
        }
    if name in ("pdf.exists", "pdf.validate"):
        ok = bool((verdict or {}).get("ok")) and bool((verdict or {}).get("valid_magic"))
        return {"ok": ok, "name": name, "why": (verdict or {}).get("why", ""), **dict(verdict or {})}
    if name in ("syntax.python", "run", "unittest", "pytest"):
        return {
            "ok": bool((verdict or {}).get("ok")),
            "name": name,
            "cmd": (verdict or {}).get("cmd", ""),
            "exit_code": (verdict or {}).get("exit_code"),
            "trivial": bool((verdict or {}).get("trivial")),
        }
    return {"ok": bool((verdict or {}).get("ok")), "name": name, **dict(verdict or {})}


def meaningful_run_evidence(command: str, exit_code: int) -> bool:
    """Exit 0 alone is insufficient if the command is a no-op for the artifact type."""
    if exit_code != 0:
        return False
    if is_trivial_command(command):
        return False
    return True


def required_validators_for_language(language: str) -> Sequence[str]:
    if language == "html":
        return ("html.render",)  # static_lint is substitute when chromium missing
    if language == "pdf":
        return ("pdf.exists",)
    if language == "python":
        return ("syntax.python",)
    return ("exists.path",)
