from __future__ import annotations

import json

import pytest

from lolm.qev_vault import (
    SCHEMA_V2, INNER_SCHEMA, VaultError, b64u_decode, b64u_encode,
    canonical_json, envelope_id, seal, unseal,
)

PAYLOAD = {"command": "explain the gate", "answer": "The gate arbitrates streams.",
           "events": 42, "verdict": "nfet_control_visible"}
PW = "correct horse battery staple"


def test_roundtrip_and_integrity():
    vault = seal(PAYLOAD, PW)
    assert vault["schema"] == SCHEMA_V2
    assert vault["kdf"]["algorithm"] == "argon2id"
    assert vault["kdf"]["opslimit"] == 4 and vault["kdf"]["memlimit"] == 100663296
    assert vault["wrap"]["algorithm"] == "XChaCha20-Poly1305"
    # b64url without padding, correct raw lengths
    assert "=" not in vault["kdf"]["salt"] and len(b64u_decode(vault["kdf"]["salt"])) == 16
    assert len(b64u_decode(vault["wrap"]["nonce"])) == 24
    assert len(b64u_decode(vault["wrap"]["wrapped_key"])) == 48  # 32B key + 16B tag
    assert len(b64u_decode(vault["content"]["nonce"])) == 24

    inner, integrity = unseal(vault, PW)
    assert inner["schema"] == INNER_SCHEMA
    assert inner["payload"] == PAYLOAD
    assert integrity["aead_authenticated"] is True
    assert integrity["payload_hash_match"] is True
    assert integrity["envelope_id"] == envelope_id(vault)


def test_wrong_passphrase_fails_cleanly():
    vault = seal(PAYLOAD, PW)
    with pytest.raises(VaultError) as err:
        unseal(vault, "not the passphrase")
    assert err.value.reason == "wrong_passphrase_or_tampered"


def test_ciphertext_tamper_detected():
    vault = seal(PAYLOAD, PW)
    ct = bytearray(b64u_decode(vault["content"]["ciphertext"]))
    ct[len(ct) // 2] ^= 0x01
    vault["content"]["ciphertext"] = b64u_encode(bytes(ct))
    with pytest.raises(VaultError) as err:
        unseal(vault, PW)
    assert err.value.reason == "wrong_passphrase_or_tampered"


def test_metadata_tamper_breaks_aad():
    vault = seal(PAYLOAD, PW)
    vault["created_at"] = "2031-01-01T00:00:00Z"  # AAD-bound field
    with pytest.raises(VaultError) as err:
        unseal(vault, PW)
    assert err.value.reason == "wrong_passphrase_or_tampered"


def test_unknown_outer_schema_rejected():
    """The exact prototype failure from the brief: app-invented outer schema."""
    vault = seal(PAYLOAD, PW)
    vault["schema"] = "qira.agent.vault.v1"
    with pytest.raises(VaultError) as err:
        unseal(vault, PW)
    assert err.value.reason == "unsupported_schema"


def test_weak_passphrase_rejected():
    with pytest.raises(VaultError) as err:
        seal(PAYLOAD, "short")
    assert err.value.reason == "weak_passphrase"


def test_canonical_json_matches_verifier_semantics():
    # recursive key sort, compact separators, raw utf-8 — mirror of chat.js
    obj = {"b": [2, {"z": 1, "a": "é"}], "a": None}
    assert canonical_json(obj) == '{"a":null,"b":[2,{"a":"é","z":1}]}'


def test_envelope_is_pure_json():
    vault = seal(PAYLOAD, PW)
    assert json.loads(json.dumps(vault)) == vault
