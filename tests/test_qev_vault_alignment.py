# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Guard against silent QEV format drift.

lolm/qev_vault.py does not import QEV — it MIRRORS the envelope format served by
secure.imagineqira.com ("mirrors /vault/chat.js on the secure site exactly"). That is
a deliberate choice (no shared runtime between a Python origin and a browser vault),
but it means the day the site ships a new format, LOLM keeps sealing envelopes the
public verifier may no longer accept, and nothing would say so.

The offline tests always run. The network check is opt-in so CI stays hermetic:

    LOLM_CHECK_QEV_LIVE=1 pytest tests/test_qev_vault_alignment.py
"""

from __future__ import annotations

import os
import re
import urllib.request

import pytest

from lolm.qev_vault import SCHEMA_V2, VAULT_VERSION, VaultError, seal, unseal

LIVE_VAULT_JS = "https://secure.imagineqira.com/vault/chat.js"


PASS = "correct horse battery staple"


def test_seal_unseal_round_trip():
    env = seal({"receipt": "demo", "sha": "abc"}, PASS)
    assert env["schema"] == SCHEMA_V2
    assert env["version"] == VAULT_VERSION
    out = unseal(env, PASS)
    payload = out[0] if isinstance(out, tuple) else out
    assert payload["payload"] == {"receipt": "demo", "sha": "abc"}


def test_wrong_passphrase_is_rejected():
    env = seal({"x": 1}, PASS)
    with pytest.raises(VaultError):
        unseal(env, "some other passphrase")


def test_short_passphrase_is_refused_at_seal_time():
    with pytest.raises(VaultError):
        seal({"x": 1}, "short")


@pytest.mark.parametrize("field", ["created_at", "mode", "schema", "version"])
def test_tampering_with_bound_metadata_breaks_the_seal(field):
    # The AAD is the canonical JSON of every field except the wrapped key and
    # ciphertext, so editing any bound field must break an AEAD tag. That property is
    # the whole reason a sealed receipt is worth more than a hash written to a log.
    env = seal({"x": 1}, PASS)
    tampered = dict(env)
    tampered[field] = "TAMPERED"
    with pytest.raises(VaultError):
        unseal(tampered, PASS)


def test_schema_is_the_v2_envelope():
    assert SCHEMA_V2 == "BRY-NFET-SX-VAULT-V2"
    assert re.fullmatch(r"\d+\.\d+\.\d+", VAULT_VERSION), VAULT_VERSION


@pytest.mark.skipif(not os.environ.get("LOLM_CHECK_QEV_LIVE"),
                    reason="set LOLM_CHECK_QEV_LIVE=1 to check against the live verifier")
def test_mirrored_version_still_matches_the_live_verifier():
    req = urllib.request.Request(LIVE_VAULT_JS, headers={"User-Agent": "lolm-qev-drift/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        js = r.read().decode("utf-8", "replace")
    schemas = set(re.findall(r"BRY-NFET-SX-VAULT-V\d+", js))
    # V99 appears in QEV's own negative tests as a deliberately bogus schema.
    schemas = {s for s in schemas if s != "BRY-NFET-SX-VAULT-V99"}
    assert SCHEMA_V2 in schemas, (
        f"the live verifier no longer advertises {SCHEMA_V2} (it has {sorted(schemas)}) — "
        f"LOLM would be sealing envelopes it cannot open")
    versions = set(re.findall(r'version"\s*:\s*"(\d+\.\d+\.\d+)"', js))
    assert VAULT_VERSION in versions, (
        f"lolm/qev_vault.py mirrors QEV {VAULT_VERSION}, but the live site now reports "
        f"{sorted(versions)}. Re-check /vault/chat.js and update the mirror, or the two "
        f"implementations have silently diverged.")
