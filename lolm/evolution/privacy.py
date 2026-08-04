# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Privacy clearing for evolution trajectories.

Bronze → Silver requires secrets and personal data removed. We reuse Track 2B
redaction patterns and add PII heuristics that fail closed when uncertain.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lolm.track2b.redact import redact_secrets, redact_text

# Heuristic PII — not exhaustive; presence blocks Gold until manual review flag.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Require separators or +country — bare 10-digit ints (timestamps, hashes) are NOT phones.
_PHONE = re.compile(
    r"(?<!\d)(?:\+1[-.\s]?|1[-.\s])?\(\d{3}\)[-.\s]?\d{3}[-.\s]?\d{4}\b"
    r"|(?<!\d)\+?\d{1,3}[-.\s]\d{2,4}[-.\s]\d{2,4}[-.\s]\d{2,4}\b"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")

# Fields we strip entirely from training payloads (never useful in weights).
_DROP_KEYS = frozenset({
    "authorization", "api_key", "apiKey", "password", "passwd", "secret",
    "token", "cookie", "set-cookie", "private_key", "access_token",
    "refresh_token", "session_id", "credit_card",
})


def scan_pii(text: str) -> List[str]:
    """Return short labels of PII classes detected in text."""
    if not text:
        return []
    hits: List[str] = []
    if _PRIVATE_KEY.search(text):
        hits.append("private_key")
    if _JWT.search(text):
        hits.append("jwt")
    if _EMAIL.search(text):
        hits.append("email")
    if _SSN.search(text):
        hits.append("ssn")
    if _PHONE.search(text):
        hits.append("phone")
    # credit card: only if Luhn-looking long digit runs (cheap heuristic)
    for m in _CC.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            hits.append("credit_card")
            break
    return hits


def _luhn_ok(digits: str) -> bool:
    try:
        nums = [int(c) for c in digits]
    except ValueError:
        return False
    checksum = 0
    parity = len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        checksum += n
    return checksum % 10 == 0


def scrub_dict(obj: Any, secrets: Optional[Sequence[str]] = None) -> Any:
    """Deep scrub: drop sensitive keys, redact secret substrings."""
    secrets = list(secrets or ())
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            kl = str(k).lower().replace("-", "_")
            if kl in _DROP_KEYS or any(s in kl for s in ("password", "secret", "token", "api_key")):
                out[k] = "***REDACTED***"
                continue
            out[k] = scrub_dict(v, secrets)
        return out
    if isinstance(obj, list):
        return [scrub_dict(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    return obj


def clear_trajectory(
    traj: Dict[str, Any],
    *,
    secrets: Optional[Sequence[str]] = None,
    allow_residual_pii: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (cleaned_trajectory, report).

    report.privacy_cleared is True only when no residual PII remains (or
    allow_residual_pii and we redacted known secrets).
    """
    secrets = list(secrets or ())
    cleaned = scrub_dict(copy.deepcopy(traj), secrets)
    cleaned = redact_secrets(cleaned, secrets)

    blob = json_safe_blob(cleaned)
    residual = scan_pii(blob)
    # After redaction, common patterns may still match placeholders — ignore REDACTED spans
    residual = [r for r in residual if r != "email" or "@" in blob.replace("***REDACTED***", "")]

    report = {
        "residual_pii": residual,
        "privacy_cleared": (not residual) or allow_residual_pii,
        "secrets_supplied": len(secrets),
    }
    cleaned["privacy_cleared"] = report["privacy_cleared"]
    return cleaned, report


def json_safe_blob(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)
