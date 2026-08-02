# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Ed25519 receipt signing with public-key rotation and persistent local keys."""
from __future__ import annotations

import base64
import hashlib
import json
import math
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
    # Telemetry attached after seal must never enter the signed core
    "shadow_telemetry",
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
    """Load private signing keys (server-side only). Never give these to runners."""
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


def _parse_verify_keys(raw: str) -> Dict[str, VerifyKey]:
    """Parse public verification keys: ``kid:base64url_public_key[,kid2:...]``."""
    out: Dict[str, VerifyKey] = {}
    for part in (raw or "").split(","):
        if ":" not in part:
            continue
        kid, pub = part.split(":", 1)
        kid, pub = kid.strip(), pub.strip()
        if not kid or not pub:
            continue
        try:
            raw_bytes = _unb64(pub)
            if len(raw_bytes) == 32:
                out[kid] = VerifyKey(raw_bytes)
                continue
        except Exception:
            pass
        try:
            raw_bytes = bytes.fromhex(pub)
            if len(raw_bytes) == 32:
                out[kid] = VerifyKey(raw_bytes)
        except Exception:
            continue
    return out


def load_verify_keys() -> Dict[str, VerifyKey]:
    """Load trusted public verification keys for runners / benchmark clients.

    Preferred env: ``LOLM_RECEIPT_VERIFY_KEYS`` (public only).

    Does **not** load private signing material. Callers that need local unit-test
    verification against ephemeral signing keys should pass verify_keys explicitly
    or set LOLM_ALLOW_UNTRUSTED_LOCAL_RECEIPTS on the adapter, not here.
    """
    configured = _parse_verify_keys(os.environ.get("LOLM_RECEIPT_VERIFY_KEYS", ""))
    if configured:
        return configured
    # Optional file of public keys (never secrets)
    path = os.environ.get("LOLM_RECEIPT_VERIFY_KEYS_FILE", "").strip()
    if path and Path(path).is_file():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            # formats: {"keys": {"kid": "b64..."}} or list of {key_id, public_key}
            if isinstance(data.get("keys"), dict):
                parts = [f"{k}:{v}" for k, v in data["keys"].items()]
                return _parse_verify_keys(",".join(parts))
            if isinstance(data.get("keys"), list):
                parts = [
                    f"{row.get('key_id')}:{row.get('public_key')}"
                    for row in data["keys"]
                    if row.get("key_id") and row.get("public_key")
                ]
                return _parse_verify_keys(",".join(parts))
        except Exception:
            pass
    return {}


def verify_keys_from_signing(keys: Optional[Dict[str, SigningKey]] = None) -> Dict[str, VerifyKey]:
    """Derive public VerifyKeys from private SigningKeys (local tests only)."""
    sks = keys if keys is not None else load_keys()
    return {kid: sk.verify_key for kid, sk in sks.items()}


def public_key_sha256(verify_key: VerifyKey) -> str:
    return hashlib.sha256(bytes(verify_key)).hexdigest()


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
    return _normalize_json_numbers(
        json.loads(canonical_bytes(filtered).decode("utf-8"))
    )


def _normalize_json_numbers(value: Any) -> Any:
    """Normalize numeric forms that JSON.parse/stringify changes in JavaScript."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("receipt contains a non-finite number")
        if value.is_integer():
            if abs(value) > 9_007_199_254_740_991:
                raise ValueError("receipt integer exceeds JavaScript safe range")
            return int(value)
        return value
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    return value


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


def verify_code_receipt(
    receipt: Dict[str, Any],
    keys: Optional[Dict[str, SigningKey]] = None,
    *,
    verify_keys: Optional[Dict[str, VerifyKey]] = None,
) -> Dict[str, Any]:
    """Verify receipt hash and Ed25519 signature.

    Prefer ``verify_keys`` (public only) for runners. Private ``keys`` are accepted
    for backward-compatible unit tests that still hold SigningKey objects.
    """
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
    pub_key_fp = ""

    # Resolve verification material: explicit verify_keys > SigningKey map > env public
    vk_map: Dict[str, VerifyKey] = {}
    if verify_keys is not None:
        vk_map = dict(verify_keys)
    elif keys is not None:
        vk_map = verify_keys_from_signing(keys)
    else:
        vk_map = load_verify_keys()
        # Local unit tests / same-process: fall back to derive from signing keys
        # only when no public trust set is configured.
        if not vk_map:
            try:
                vk_map = verify_keys_from_signing(load_keys())
            except Exception:
                vk_map = {}

    if signature.get("alg") == "Ed25519" and signature.get("sig"):
        if kid not in vk_map:
            signature_valid = None
            reason = "unknown_key"
        else:
            try:
                vk_map[kid].verify(blob, _unb64(str(signature["sig"])))
                signature_valid = True
                reason = "ok"
                pub_key_fp = public_key_sha256(vk_map[kid])
            except (BadSignatureError, ValueError):
                signature_valid = False
                reason = "bad_signature"
                try:
                    pub_key_fp = public_key_sha256(vk_map[kid])
                except Exception:
                    pub_key_fp = ""
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
        "public_key_sha256": pub_key_fp,
        "timestamp_valid": timestamp_valid,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "integrity": {"verified": verified, "method": "sha256+Ed25519-v2"},
        "trusted_key_ids": sorted(vk_map.keys()),
    }


def public_key_status() -> Dict[str, Any]:
    keys = load_keys()
    return {
        "schema": "lolm.receipt.keys.v1",
        "active_key_id": active_kid(keys),
        "keys": [
            {
                "key_id": kid,
                "alg": "Ed25519",
                "public_key": _b64(bytes(key.verify_key)),
                "public_key_sha256": public_key_sha256(key.verify_key),
            }
            for kid, key in sorted(keys.items())
        ],
    }
