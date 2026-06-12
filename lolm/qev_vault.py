# Copyright (c) 2026 Qira LLC. All rights reserved.
# No commercial use, reproduction, hosting, redistribution, derivative
# product, or competing service use is authorized except under a written
# license signed by Qira LLC.
"""QEV sealing for AI runs — BRY-NFET-SX-VAULT-V2, byte-compatible with
the official verifier at secure.imagineqira.com.

Format (mirrors /vault/chat.js on the secure site exactly):

    outer schema:  BRY-NFET-SX-VAULT-V2     (official envelope)
    inner schema:  qira.agent.vault.v1      (app-specific payload, inside
                                             the decrypted plaintext)

    1. fresh random 32-byte vault_key per vault
    2. passphrase -> Argon2id(opslimit=4, memlimit=96 MiB) -> wrap_key
    3. wrap_key wraps vault_key   via XChaCha20-Poly1305 (wrap nonce + AAD)
    4. vault_key encrypts content via XChaCha20-Poly1305 (content nonce, SAME AAD)

    AAD is not stored: it is the canonical JSON (recursively sorted keys,
    compact separators) of all metadata EXCEPT wrapped_key/ciphertext, so
    tampering with any bound field breaks at least one AEAD tag.

Architecture rule from the product brief: apps define inner payloads; no
Qira app invents its own outer encrypted format. What QEV proves and what
it does not: AEAD + hash verify ARTIFACT INTEGRITY AND CUSTODY — they never
prove the model's answer was factually correct.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any, Dict, Tuple

from nacl import pwhash
from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
)

SCHEMA_V2 = "BRY-NFET-SX-VAULT-V2"
INNER_SCHEMA = "qira.agent.vault.v1"
AEAD_ALG = "XChaCha20-Poly1305"          # brand title-case, as the verifier expects
KDF_ALG = "argon2id"
KDF_OPSLIMIT = 4
KDF_MEMLIMIT = 100663296                  # 96 MiB — matches the verifier defaults
VAULT_VERSION = "0.28.1"                  # format lineage version mirrored from the site


class VaultError(Exception):
    """Clean failure: malformed envelope, wrong passphrase, or tampering."""

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


# -- encoding helpers (libsodium URLSAFE_NO_PADDING equivalents) --------------

def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def canonical_json(value: Any) -> str:
    """Byte-identical to the verifier's canonicalJSON: recursive key sort,
    compact separators, raw (non-ascii-escaped) UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _build_aad_v2(vault: Dict[str, Any]) -> bytes:
    aad_obj = {
        "content": {
            "algorithm": vault["content"]["algorithm"],
            "nonce": vault["content"]["nonce"],
        },
        "created_at": vault["created_at"],
        "kdf": {
            "algorithm": vault["kdf"]["algorithm"],
            "memlimit": vault["kdf"]["memlimit"],
            "opslimit": vault["kdf"]["opslimit"],
            "salt": vault["kdf"]["salt"],
        },
        "mode": vault["mode"],
        "schema": vault["schema"],
        "version": vault["version"],
        "wrap": {
            "algorithm": vault["wrap"]["algorithm"],
            "nonce": vault["wrap"]["nonce"],
        },
    }
    return canonical_json(aad_obj).encode("utf-8")


def _derive_wrap_key(passphrase: str, salt: bytes) -> bytes:
    return pwhash.argon2id.kdf(
        32, passphrase.encode("utf-8"), salt,
        opslimit=KDF_OPSLIMIT, memlimit=KDF_MEMLIMIT,
    )


def envelope_id(vault: Dict[str, Any]) -> str:
    """Human identifier: SHA-256 hex of the canonical JSON of the envelope."""
    return hashlib.sha256(canonical_json(vault).encode("utf-8")).hexdigest()


# -- public API ----------------------------------------------------------------

def seal(payload: Dict[str, Any], passphrase: str, *, mode: str = "self") -> Dict[str, Any]:
    """Seal an app payload into an official BRY-NFET-SX-VAULT-V2 envelope.

    The payload is wrapped as the qira.agent.vault.v1 inner document, with a
    SHA-256 of the payload recorded inside the plaintext so verification can
    report integrity of the inner document independently.
    """
    if not isinstance(passphrase, str) or len(passphrase) < 8:
        raise VaultError("passphrase must be at least 8 characters", "weak_passphrase")
    if mode not in ("self", "share"):
        raise VaultError("mode must be 'self' or 'share'", "bad_mode")

    inner = {
        "schema": INNER_SCHEMA,
        "sealed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": payload,
    }
    inner["payload_sha256"] = hashlib.sha256(
        canonical_json(payload).encode("utf-8")).hexdigest()
    plaintext = json.dumps(inner, ensure_ascii=False).encode("utf-8")

    salt = secrets.token_bytes(16)
    wrap_nonce = secrets.token_bytes(24)
    content_nonce = secrets.token_bytes(24)
    vault_key = secrets.token_bytes(32)

    vault: Dict[str, Any] = {
        "schema": SCHEMA_V2,
        "version": VAULT_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": mode,
        "kdf": {
            "algorithm": KDF_ALG,
            "opslimit": KDF_OPSLIMIT,
            "memlimit": KDF_MEMLIMIT,
            "salt": b64u_encode(salt),
        },
        "wrap": {
            "algorithm": AEAD_ALG,
            "nonce": b64u_encode(wrap_nonce),
        },
        "content": {
            "algorithm": AEAD_ALG,
            "nonce": b64u_encode(content_nonce),
        },
    }
    aad = _build_aad_v2(vault)
    wrap_key = _derive_wrap_key(passphrase, salt)
    vault["wrap"]["wrapped_key"] = b64u_encode(
        crypto_aead_xchacha20poly1305_ietf_encrypt(vault_key, aad, wrap_nonce, wrap_key))
    vault["content"]["ciphertext"] = b64u_encode(
        crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, aad, content_nonce, vault_key))
    return vault


def unseal(vault: Dict[str, Any], passphrase: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Open an envelope. Returns (inner_document, integrity_report).

    The integrity report says exactly what was verified — and nothing more:
    AEAD authentication and inner-hash match prove the artifact is intact;
    they do NOT prove the answer inside is true.
    """
    try:
        if vault.get("schema") != SCHEMA_V2:
            raise VaultError(
                f"unsupported vault schema: {vault.get('schema')!r} (expected {SCHEMA_V2})",
                "unsupported_schema")
        for section, fields in (("kdf", ("algorithm", "opslimit", "memlimit", "salt")),
                                ("wrap", ("algorithm", "nonce", "wrapped_key")),
                                ("content", ("algorithm", "nonce", "ciphertext"))):
            block = vault.get(section)
            if not isinstance(block, dict) or any(f not in block for f in fields):
                raise VaultError(f"vault malformed: incomplete {section} block", "malformed")
        if vault["kdf"]["algorithm"] != KDF_ALG:
            raise VaultError("unsupported kdf", "unsupported_kdf")
        if vault["wrap"]["algorithm"] != AEAD_ALG or vault["content"]["algorithm"] != AEAD_ALG:
            raise VaultError("unsupported aead algorithm", "unsupported_aead")

        aad = _build_aad_v2(vault)
        wrap_key = _derive_wrap_key(passphrase, b64u_decode(vault["kdf"]["salt"]))
        try:
            vault_key = crypto_aead_xchacha20poly1305_ietf_decrypt(
                b64u_decode(vault["wrap"]["wrapped_key"]), aad,
                b64u_decode(vault["wrap"]["nonce"]), wrap_key)
            plaintext = crypto_aead_xchacha20poly1305_ietf_decrypt(
                b64u_decode(vault["content"]["ciphertext"]), aad,
                b64u_decode(vault["content"]["nonce"]), vault_key)
        except Exception:
            # One clean reason: AEAD cannot distinguish a wrong passphrase
            # from tampered data — and claiming otherwise would be dishonest.
            raise VaultError(
                "authentication failed: wrong passphrase or tampered vault",
                "wrong_passphrase_or_tampered")
    except VaultError:
        raise
    except Exception as exc:  # malformed b64, bad types, ...
        raise VaultError(f"vault malformed: {exc}", "malformed")

    inner = json.loads(plaintext.decode("utf-8"))
    integrity = {
        "aead_authenticated": True,
        "schema": SCHEMA_V2,
        "inner_schema": inner.get("schema"),
        "envelope_id": envelope_id(vault),
    }
    expected = inner.get("payload_sha256")
    if expected:
        actual = hashlib.sha256(
            canonical_json(inner.get("payload", {})).encode("utf-8")).hexdigest()
        integrity["payload_hash_match"] = actual == expected
    return inner, integrity
