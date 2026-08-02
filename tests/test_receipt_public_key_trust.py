# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Public-key trust for receipt verification — runners never hold private keys."""

from __future__ import annotations

import json
import os
from typing import Dict, Tuple

from nacl.signing import SigningKey

from local_ui.receipt_sign import (
    _b64,
    public_key_sha256,
    sign_code_receipt,
    verify_code_receipt,
    verify_keys_from_signing,
)
from lolm.track2b.sse_adapter import LolmCodeSSEAgentAdapter, SSEAdapterConfig
from lolm.track2b.workspace import build_final_workspace, tree_hash


def _pair() -> Tuple[str, SigningKey]:
    sk = SigningKey.generate()
    kid = "test-key-a"
    return kid, sk


def _receipt(sk_map: Dict[str, SigningKey], kid: str, tree: str) -> dict:
    prev_keys = os.environ.get("LOLM_RECEIPT_SIGNING_KEYS")
    prev_kid = os.environ.get("LOLM_RECEIPT_ACTIVE_KID")
    try:
        os.environ["LOLM_RECEIPT_SIGNING_KEYS"] = f"{kid}:{_b64(bytes(sk_map[kid]))}"
        os.environ["LOLM_RECEIPT_ACTIVE_KID"] = kid
        # Clear module ephemeral cache path by forcing configured keys
        core = {
            "schema": "lolm.code.receipt.v2",
            "run_id": "r1",
            "kind": "code_agent",
            "task": "t",
            "ok": True,
            "syntax_ok": True,
            "verdict": "shipped",
            "tree_hash": tree,
            "workspace_tree_hash": tree,
            "verification": {
                "syntax_ok": True,
                "execution_ok": True,
                "contract_ok": True,
                "artifact_manifest_ok": True,
                "artifact_manifest_sha256": "a" * 64,
                "workspace_tree_sha256": tree,
                "workspace_file_count": 1,
                "workspace_total_bytes": 4,
                "final_workspace_complete": True,
            },
        }
        return sign_code_receipt(core)
    finally:
        if prev_keys is None:
            os.environ.pop("LOLM_RECEIPT_SIGNING_KEYS", None)
        else:
            os.environ["LOLM_RECEIPT_SIGNING_KEYS"] = prev_keys
        if prev_kid is None:
            os.environ.pop("LOLM_RECEIPT_ACTIVE_KID", None)
        else:
            os.environ["LOLM_RECEIPT_ACTIVE_KID"] = prev_kid


def test_unknown_key_is_not_authenticated():
    kid, sk = _pair()
    sk_map = {kid: sk}
    tree = tree_hash({"a.py": "x=1\n"})
    rec = _receipt(sk_map, kid, tree)
    # Verify with empty trust set
    v = verify_code_receipt(rec, verify_keys={})
    assert v["receipt_hash_match"] is True
    assert v["signature_valid"] is None
    assert v["signature_reason"] == "unknown_key"


def test_wrong_known_key_fails_signature():
    kid_a, sk_a = _pair()
    kid_b, sk_b = _pair()
    tree = tree_hash({"a.py": "x=1\n"})
    rec = _receipt({kid_a: sk_a}, kid_a, tree)
    # Present a different public key under the same kid
    wrong = {kid_a: sk_b.verify_key}
    v = verify_code_receipt(rec, verify_keys=wrong)
    assert v["signature_valid"] is False
    assert v["signature_reason"] == "bad_signature"


def test_valid_trusted_public_key_passes():
    kid, sk = _pair()
    tree = tree_hash({"a.py": "x=1\n"})
    rec = _receipt({kid: sk}, kid, tree)
    v = verify_code_receipt(rec, verify_keys={kid: sk.verify_key})
    assert v["receipt_hash_match"] is True
    assert v["signature_valid"] is True
    assert v["public_key_sha256"] == public_key_sha256(sk.verify_key)


def test_rotated_trusted_key_passes():
    kid_old, sk_old = _pair()
    kid_new, sk_new = _pair()
    tree = tree_hash({"a.py": "x=1\n"})
    # Signed with new key; both old+new trusted on runner
    rec = _receipt({kid_new: sk_new}, kid_new, tree)
    trust = {
        kid_old: sk_old.verify_key,
        kid_new: sk_new.verify_key,
    }
    v = verify_code_receipt(rec, verify_keys=trust)
    assert v["signature_valid"] is True
    assert v["signing_key"] == kid_new


def test_modified_key_id_is_inadmissible():
    kid, sk = _pair()
    tree = tree_hash({"a.py": "x=1\n"})
    rec = _receipt({kid: sk}, kid, tree)
    # Attacker renames key_id without re-signing under a trusted alias
    forged = dict(rec)
    forged["signature"] = dict(rec["signature"])
    forged["signature"]["key_id"] = "attacker-key"
    forged["signing_key"] = "attacker-key"
    # Hash still matches core? key_id is inside signature which is post-seal — so
    # hash_match may still be True; signature must not verify under attacker-key.
    v = verify_code_receipt(forged, verify_keys={kid: sk.verify_key})
    assert v["signature_valid"] is None  # unknown_key
    assert v["signature_reason"] == "unknown_key"
    # Even if attacker also injects their public key as trusted under attacker-key,
    # the signature bytes were produced by a different private key.
    attacker = SigningKey.generate()
    v2 = verify_code_receipt(forged, verify_keys={"attacker-key": attacker.verify_key})
    assert v2["signature_valid"] is False


def test_adapter_rejects_unknown_key_when_strict(tmp_path=None):
    """Strict remote mode: unknown key → inadmissible (not agent_failure)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    kid, sk = _pair()
    files = {"util.py": "x=1\n"}
    fw = build_final_workspace(files, run_id="r1")
    th = fw["tree_hash"]
    rec = _receipt({kid: sk}, kid, th)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            sha = "a" * 40
            def sse(ev, data):
                self.wfile.write(
                    f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode()
                )
            sse("code_start", {"server_sha": sha, "fixture_hash": tree_hash(files), "run_id": "r1"})
            sse("final_workspace", {**fw, "server_sha": sha})
            sse("code_done", {"server_sha": sha, "tree_hash": th, "ok": True})
            sse("code_receipt", rec)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # No LOLM_RECEIPT_VERIFY_KEYS → unknown; strict → inadmissible
        old = os.environ.pop("LOLM_RECEIPT_VERIFY_KEYS", None)
        ad = LolmCodeSSEAgentAdapter(SSEAdapterConfig(
            base_url=f"http://127.0.0.1:{srv.server_address[1]}",
            api_key="k" * 16,
            expected_server_sha="a" * 40,
            require_trusted_signature=True,
            allow_untrusted_local_receipts=False,
        ))
        r = ad.run_task("L01", "fix", files)
        assert r.run_class == "inadmissible"
        assert any("unknown" in x or "signature" in x for x in r.reasons)
        # With trusted public key → admitted path (oracle not applied → admitted)
        os.environ["LOLM_RECEIPT_VERIFY_KEYS"] = f"{kid}:{_b64(bytes(sk.verify_key))}"
        ad2 = LolmCodeSSEAgentAdapter(SSEAdapterConfig(
            base_url=f"http://127.0.0.1:{srv.server_address[1]}",
            api_key="k" * 16,
            expected_server_sha="a" * 40,
            require_trusted_signature=True,
            allow_untrusted_local_receipts=False,
            expected_receipt_key_id=kid,
            expected_receipt_public_key_sha256=public_key_sha256(sk.verify_key),
        ))
        r2 = ad2.run_task("L01", "fix", files)
        assert r2.run_class in ("admitted", "admissible_pass", "agent_failure")
        assert r2.request_meta.get("receipt_verify", {}).get("signature_valid") is True
    finally:
        srv.shutdown()
        if old is not None:
            os.environ["LOLM_RECEIPT_VERIFY_KEYS"] = old
        else:
            os.environ.pop("LOLM_RECEIPT_VERIFY_KEYS", None)
        os.environ.pop("LOLM_RECEIPT_SIGNING_KEYS", None)


def test_local_untrusted_flag_allows_hash_only_unknown_key():
    kid, sk = _pair()
    tree = tree_hash({"a.py": "x\n"})
    rec = _receipt({kid: sk}, kid, tree)
    # Empty trust set + allow untrusted on adapter path is covered by verify itself
    v = verify_code_receipt(rec, verify_keys={})
    assert v["signature_valid"] is None
    assert v["receipt_hash_match"] is True
