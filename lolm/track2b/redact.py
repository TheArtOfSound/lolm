# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Secret redaction for Track 2B harness artifacts and exception strings."""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Sequence


_REDACT = "***REDACTED***"


def _patterns(secrets: Sequence[str]) -> list[re.Pattern[str]]:
    pats: list[re.Pattern[str]] = []
    for s in secrets:
        s = (s or "").strip()
        if len(s) < 4:
            continue
        pats.append(re.compile(re.escape(s)))
    # Common bearer shapes even if full key unknown in nested blobs
    pats.append(re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+"))
    pats.append(re.compile(r"(?i)(x-lolm-api-key\s*[:=]\s*)\S+"))
    pats.append(re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[\"']?[A-Za-z0-9_\-]{12,}"))
    return pats


def redact_text(text: str, secrets: Optional[Sequence[str]] = None) -> str:
    if not text:
        return text
    out = str(text)
    for pat in _patterns(secrets or ()):
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + _REDACT, out)
        else:
            out = pat.sub(_REDACT, out)
    return out


def redact_secrets(obj: Any, secrets: Optional[Sequence[str]] = None) -> Any:
    """Deep-copy structure with secret substrings removed."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    if isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {
            redact_text(str(k), secrets) if isinstance(k, str) else k: redact_secrets(v, secrets)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact_secrets(v, secrets) for v in obj]
    return redact_text(str(obj), secrets)


def secrets_present(obj: Any, secrets: Sequence[str]) -> list[str]:
    """Return list of secret values found as substrings in serialized obj."""
    found: list[str] = []
    blob = str(obj)
    for s in secrets:
        s = (s or "").strip()
        if len(s) >= 8 and s in blob:
            found.append(s[:4] + "…")
    return found
