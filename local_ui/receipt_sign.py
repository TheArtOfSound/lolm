# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Ed25519 receipt signing with public-key rotation and persistent local keys."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

_KEY_FILE: Optional[Path] = None
_EPHEMERAL: Optional[Dict[str, SigningKey]] = None
_POST_SEAL = {
    "receipt_sha", "signature", "signing_key",
    "ledger_sha", "prev_ledger_sha", "ledger_ts", "source", "demo", "selftest",
}


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def content_sha256(blob: bytes, n: int = 64) -> str:
    return hashlib.sha256(blob).hexdigest()[:n]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    value = (value or "").strip()
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _seed(value: str) -> bytes:
    value = (value or "").strip()
    try:
        raw = bytes.fromhex(value)
        if len(raw) == 32:
            return raw
    except ValueError:
        pass
    try:
        raw = _unb64(value)
        if len(raw) == 32:
            return raw
    except Exception:
        pass
    return hashlib.sha256(value.encode("utf-8")).digest()


def _parse_keys(raw: str) -> Dict[str, SigningKey]:
    out: Dict[str, SigningKey] = {}
    for part in (raw or "").split(","):
        if ":" not in part:
            continue
        kid, secret = part.split(":", 1)
        kid, secret = kid.strip(), secret.strip()
        if kid and secret:
            out[kid] = SigningKey(_seed(secret))
    return out


def init(root: Path) -> None:
    """Load or create a persistent 0600 signing seed for self-hosted operation."""
    global _KEY_FILE
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _KEY_FILE = root / "receipt_signing_ed25519.json"
    if os.environ.get("LOLM_RECEIPT_SIGNING_KEYS", "").strip() or _KEY_FILE.exists():
        return
    kid = f"local-{time.strftime('%Y-%m', time.gmtime())}"
    payload = {"active_kid": kid, "keys": {kid: _b64(secrets.token_bytes(32))}}
    tmp = _KEY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, _KEY_FILE)


def load_keys() -> Dict[str, SigningKey]:
    global _EPHEMERAL
    configured = _parse_keys(os.environ.get("LOLM_RECEIPT_SIGNING_KEYS", ""))
    if configured:
        return configured
    if _KEY_FILE and _KEY_FILE.exists():
        try:
            data = json.loads(_KEY_FILE.read_text(encoding="utf-8"))
            return {kid: SigningKey(_seed(seed)) for kid, seed in (data.get("keys") or {}).items()}
        except Exception:
            pass
    if _EPHEMERAL is None:
        _EPHEMERAL = {"ephemeral-test": SigningKey.generate()}
    return _EPHEMERAL


def active_kid(keys: Optional[Dict[str, SigningKey]] = None) -> Optional[str]:
    keys = keys if keys is not None else load_keys()
    requested = os.environ.get("LOLM_RECEIPT_ACTIVE_KID", "").strip()
    if requested in keys:
        return requested
    if _KEY_FILE and _KEY_FILE.exists():
        try:
            requested = str(json.loads(_KEY_FILE.read_text()).get("active_kid") or "")
            if requested in keys:
                return requested
        except Exception:
            pass
    return sorted(keys)[-1] if keys else None


def _signed_core(receipt: Dict[str, Any]) -> Dict[str, Any]:
    filtered = {
        key: value for key, value in (receipt or {}).items()
        if key not in _POST_SEAL
    }
    # Signing must return an immutable-by-construction snapshot. Agent control
    # timelines and task-state blobs contain nested lists that can advance after
    # the receipt is built; a shallow dict copy lets those later mutations
    # invalidate the already-computed hash and signature.
    return json.loads(canonical_bytes(filtered).decode("utf-8"))


def sign_code_receipt(core: Dict[str, Any]) -> Dict[str, Any]:
    out = _signed_core(dict(core or {}))
    keys = load_keys()
    kid = active_kid(keys)
    if not kid:
        raise RuntimeError("no receipt signing key available")
    out["signed_at"] = int(time.time())
    blob = canonical_bytes(out)
    out["receipt_sha"] = content_sha256(blob)
    out["signature"] = {
        "alg": "Ed25519",
        "key_id": kid,
        "sig": _b64(keys[kid].sign(blob).signature),
    }
    out["signing_key"] = kid
    return out


def verify_code_receipt(receipt: Dict[str, Any],
                        keys: Optional[Dict[str, SigningKey]] = None) -> Dict[str, Any]:
    row = dict(receipt or {})
    core = _signed_core(row)
    blob = canonical_bytes(core)
    expected = content_sha256(blob)
    claimed = row.get("receipt_sha")
    hash_match = isinstance(claimed, str) and claimed == expected
    signature = row.get("signature") if isinstance(row.get("signature"), dict) else {}
    kid = str(signature.get("key_id") or signature.get("kid") or "")
    signature_valid: Optional[bool] = False
    reason = "missing_or_unsupported_signature"
    available = keys if keys is not None else load_keys()
    if signature.get("alg") == "Ed25519" and signature.get("sig"):
        if kid not in available:
            signature_valid = None
            reason = "unknown_key"
        else:
            try:
                available[kid].verify_key.verify(blob, _unb64(str(signature["sig"])))
                signature_valid = True
                reason = "ok"
            except (BadSignatureError, ValueError):
                signature_valid = False
                reason = "bad_signature"
    verification = row.get("verification") or {}
    signed_at = row.get("signed_at")
    timestamp_valid = (
        isinstance(signed_at, int)
        and not isinstance(signed_at, bool)
        and signed_at > 0
        and signed_at <= int(time.time()) + 300
    )
    code_ok = (
        row.get("schema") == "lolm.code.receipt.v2"
        and bool(row.get("run_id"))
        and row.get("verdict") == "shipped"
        and row.get("ok") is True
        and row.get("syntax_ok") is True
        and verification.get("syntax_ok") is True
        and verification.get("execution_ok") is True
        and verification.get("contract_ok") is True
        and verification.get("artifact_manifest_ok") is True
        and len(str(verification.get("artifact_manifest_sha256") or "")) == 64
    )
    visual_ok = (
        row.get("schema") == "lolm.visual.receipt.v2"
        and bool(row.get("run_id"))
        and row.get("verdict") == "verified"
        and row.get("ok") is True
        and verification.get("browser_ok") is True
        and len(str(verification.get("html_sha256") or "")) == 64
    )
    verified = bool(hash_match and signature_valid is True and timestamp_valid
                    and (code_ok or visual_ok))
    return {
        "schema_valid": row.get("schema") in ("lolm.code.receipt.v2", "lolm.visual.receipt.v2"),
        "receipt_hash_match": hash_match,
        "expected_sha": expected,
        "claimed_sha": claimed,
        "signature_valid": signature_valid,
        "signing_key": kid or None,
        "signature_reason": reason,
        "timestamp_valid": timestamp_valid,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "integrity": {"verified": verified, "method": "sha256+Ed25519-v2"},
    }


def public_key_status() -> Dict[str, Any]:
    keys = load_keys()
    return {
        "schema": "lolm.receipt.keys.v1",
        "active_key_id": active_kid(keys),
        "keys": [
            {"key_id": kid, "alg": "Ed25519", "public_key": _b64(bytes(key.verify_key))}
            for kid, key in sorted(keys.items())
        ],
    }
