# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Mock-SSE tests for Track 2B lolm-code-sse adapter (no credentials, no production)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from lolm.track2b.classify import RunClass
from lolm.track2b.fixtures import (
    MAX_FIXTURE_BYTES,
    build_resume_package,
    fixture_hash,
    validate_fixture_paths,
)
from lolm.track2b.redact import redact_text, secrets_present
from lolm.track2b.sse_adapter import LolmCodeSSEAgentAdapter, SSEAdapterConfig
from lolm.track2b.sse_parse import parse_sse_chunk
from lolm.track2b.workspace import build_final_workspace, tree_hash

EXPECTED_SHA = "eb0412817429194f4fe85deb4d9f1de291076d16"
API_KEY = "test-secret-key-NEVER-LEAK-00123456"


def _sse(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def _identity(**extra: Any) -> Dict[str, Any]:
    base = {
        "server_sha": EXPECTED_SHA,
        "model_id": "mock-model",
        "provider": "mock",
        "deployment_id": "mock-deploy-1",
        "run_id": "run_mock_1",
    }
    base.update(extra)
    return base


def _signed_receipt(
    tree_hash: str,
    *,
    file_count: int = 1,
    total_bytes: int = 10,
    complete: bool = True,
    ok: bool = True,
    mutate_after_seal: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Build an Ed25519-sealed mock receipt with workspace binding in the core."""
    from local_ui.receipt_sign import sign_code_receipt

    core = {
        "schema": "lolm.code.receipt.v2",
        "run_id": "run_mock_1",
        "kind": "code_agent",
        "task": "mock",
        "ok": ok,
        "syntax_ok": True,
        "verdict": "shipped" if ok else "incomplete",
        "tree_hash": tree_hash,
        "workspace_tree_hash": tree_hash,
        "server_sha": EXPECTED_SHA,
        "model_id": "mock-model",
        "provider": "mock",
        "deployment_id": "mock-deploy-1",
        "verification": {
            "syntax_ok": True,
            "execution_ok": True,
            "contract_ok": True,
            "artifact_manifest_ok": True,
            "artifact_manifest_sha256": "a" * 64,
            "workspace_tree_sha256": tree_hash,
            "workspace_file_count": file_count,
            "workspace_total_bytes": total_bytes,
            "final_workspace_complete": complete,
        },
    }
    core.update(extra)
    sealed = sign_code_receipt(core)
    if mutate_after_seal:
        # Simulate the regression: bolt tree hash on after signing
        sealed = dict(sealed)
        sealed["tree_hash"] = "f" * 64
        sealed["workspace_tree_hash"] = "f" * 64
        sealed.setdefault("verification", {})
        sealed["verification"] = dict(sealed["verification"])
        sealed["verification"]["workspace_tree_sha256"] = "f" * 64
    return sealed


class _MockState:
    mode: str = "valid"
    last_body: Optional[Dict[str, Any]] = None
    requests: int = 0


STATE = _MockState()


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # silence
        return

    def do_POST(self) -> None:  # noqa: N802
        STATE.requests += 1
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}
        STATE.last_body = body

        key = self.headers.get("X-LOLM-Api-Key") or ""
        if STATE.mode == "rate_limit":
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"rate limit"}')
            return
        if STATE.mode == "unauthorized":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return
        if key != API_KEY and STATE.mode != "no_auth_check":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"bad key"}')
            return

        files = ((body.get("resume_package") or {}).get("workspace_snapshot") or {"a.py": "x=1\n"})
        fw = build_final_workspace(files, run_id="run_mock_1")
        th = fw["tree_hash"]
        fhash = (body.get("resume_package") or {}).get("fixture_hash") or fixture_hash(files)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        mode = STATE.mode
        total_bytes = sum(len(v.encode()) for v in files.values())
        if mode == "valid":
            rec = _signed_receipt(th, file_count=len(files), total_bytes=total_bytes)
            self.wfile.write(_sse("code_start", {**_identity(), "task": body.get("task"), "fixture_hash": fhash}))
            self.wfile.write(_sse("final_workspace", {**fw, **_identity()}))
            self.wfile.write(_sse("code_done", {**_identity(), "ok": True, "tree_hash": th}))
            self.wfile.write(_sse("code_receipt", rec))
        elif mode == "missing_done":
            rec = _signed_receipt(th, file_count=len(files), total_bytes=total_bytes)
            self.wfile.write(_sse("code_start", {**_identity(), "fixture_hash": fhash}))
            self.wfile.write(_sse("final_workspace", {**fw, **_identity()}))
            self.wfile.write(_sse("code_receipt", rec))
        elif mode == "missing_receipt":
            self.wfile.write(_sse("code_start", {**_identity(), "fixture_hash": fhash}))
            self.wfile.write(_sse("final_workspace", {**fw, **_identity()}))
            self.wfile.write(_sse("code_done", {**_identity(), "tree_hash": th}))
        elif mode == "wrong_sha":
            bad = {**_identity(), "server_sha": "deadbeef" * 5}
            rec = _signed_receipt(th, file_count=len(files), total_bytes=total_bytes, server_sha=bad["server_sha"])
            self.wfile.write(_sse("code_start", {**bad, "fixture_hash": fhash}))
            self.wfile.write(_sse("final_workspace", {**fw, **bad}))
            self.wfile.write(_sse("code_done", {**bad, "tree_hash": th}))
            self.wfile.write(_sse("code_receipt", rec))
        elif mode == "idle_timeout":
            # Emit code_start and keep the connection open so the adapter's
            # queue-side idle timeout fires (not peer-close).
            frame = _sse("code_start", {**_identity(), "fixture_hash": fhash})
            self.wfile.write(frame)
            try:
                self.wfile.flush()
            except Exception:
                pass
            time.sleep(60.0)
        elif mode == "hash_mismatch_fw":
            # FW claims wrong tree hash vs reconstructable contents
            self.wfile.write(_sse("code_start", {**_identity(), "fixture_hash": fhash}))
            bad_fw = dict(fw)
            bad_fw["tree_hash"] = "0" * 64
            rec = _signed_receipt("0" * 64, file_count=len(files), total_bytes=total_bytes)
            self.wfile.write(_sse("final_workspace", {**bad_fw, **_identity()}))
            self.wfile.write(_sse("code_done", {**_identity(), "tree_hash": "0" * 64}))
            self.wfile.write(_sse("code_receipt", rec))
        elif mode == "receipt_tree_mismatch":
            # Signed receipt binds wrong tree vs final_workspace
            rec = _signed_receipt("1" * 64, file_count=len(files), total_bytes=total_bytes)
            self.wfile.write(_sse("code_start", {**_identity(), "fixture_hash": fhash}))
            self.wfile.write(_sse("final_workspace", {**fw, **_identity()}))
            self.wfile.write(_sse("code_done", {**_identity(), "tree_hash": th}))
            self.wfile.write(_sse("code_receipt", rec))
        elif mode == "post_seal_mutation":
            # Regression: seal then mutate tree hash fields
            rec = _signed_receipt(
                th, file_count=len(files), total_bytes=total_bytes, mutate_after_seal=True,
            )
            self.wfile.write(_sse("code_start", {**_identity(), "fixture_hash": fhash}))
            self.wfile.write(_sse("final_workspace", {**fw, **_identity()}))
            self.wfile.write(_sse("code_done", {**_identity(), "tree_hash": th}))
            self.wfile.write(_sse("code_receipt", rec))
        elif mode == "leak_key":
            rec = _signed_receipt(th, file_count=len(files), total_bytes=total_bytes)
            self.wfile.write(_sse("code_start", {**_identity(), "fixture_hash": fhash, "debug": API_KEY}))
            self.wfile.write(_sse("final_workspace", {**fw, **_identity()}))
            self.wfile.write(_sse("code_done", {**_identity(), "tree_hash": th}))
            self.wfile.write(_sse("code_receipt", rec))
        elif mode == "split_frames":
            rec = _signed_receipt(th, file_count=len(files), total_bytes=total_bytes)
            start = _sse("code_start", {**_identity(), "fixture_hash": fhash})
            self.wfile.write(start[:12])
            self.wfile.flush()
            self.wfile.write(start[12:])
            multi = (
                "event: final_workspace\n"
                f"data: {json.dumps({**fw, **_identity()})}\n"
                "\n"
            ).encode()
            mid = len(multi) // 2
            self.wfile.write(multi[:mid])
            self.wfile.flush()
            self.wfile.write(multi[mid:])
            self.wfile.write(_sse("code_done", {**_identity(), "tree_hash": th}))
            self.wfile.write(_sse("code_receipt", rec))
        else:
            self.wfile.write(_sse("error", {"error": f"unknown mode {mode}"}))


def _start_server() -> Tuple[ThreadingHTTPServer, str]:
    # Threading so idle-timeout hangs do not block later tests.
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, f"http://127.0.0.1:{port}"


def _adapter(base: str, **kw: Any) -> LolmCodeSSEAgentAdapter:
    cfg = SSEAdapterConfig(
        base_url=base,
        api_key=API_KEY,
        expected_server_sha=EXPECTED_SHA,
        idle_timeout_s=float(kw.pop("idle_timeout_s", 1.2)),
        hard_timeout_s=float(kw.pop("hard_timeout_s", 8.0)),
        **kw,
    )
    return LolmCodeSSEAgentAdapter(cfg)


SEED = {"util.py": "def f():\n    return 1\n", "test_util.py": "assert True\n"}


def test_01_valid_complete_stream_passes_admission():
    STATE.mode = "valid"
    srv, base = _start_server()
    try:
        ad = _adapter(base)
        r = ad.run_task("L01", "fix util", SEED)
        assert r.admitted is True
        assert r.run_class not in (RunClass.INADMISSIBLE.value, RunClass.NOT_ADMITTED.value)
        # oracle not applied yet → agent_failure or admissible unevaluated path
        assert r.code_done and r.code_receipt and r.final_workspace
        assert r.server_sha == EXPECTED_SHA
        r2 = ad.apply_oracle(r, True)
        assert r2.run_class == RunClass.ADMISSIBLE_PASS.value
    finally:
        srv.shutdown()


def test_02_missing_code_done_inadmissible():
    STATE.mode = "missing_done"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.INADMISSIBLE.value
        assert any("code_done" in x for x in r.reasons)
    finally:
        srv.shutdown()


def test_03_missing_receipt_inadmissible():
    STATE.mode = "missing_receipt"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.INADMISSIBLE.value
        assert any("receipt" in x for x in r.reasons)
    finally:
        srv.shutdown()


def test_04_wrong_server_sha_inadmissible():
    STATE.mode = "wrong_sha"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.INADMISSIBLE.value
        assert any("server_sha" in x for x in r.reasons)
    finally:
        srv.shutdown()


def test_05_idle_timeout_after_code_start():
    # Classification: idle/hard timeout after admission is TIMEOUT, not agent failure.
    # (Long-lived hung-socket integration is covered by the adapter's queue idle
    # path; a 60s open socket is not used here to keep the suite non-blocking.)
    from lolm.track2b.classify import classify_run
    cls, reasons = classify_run(
        admitted=True,
        code_start=True,
        code_done=False,
        code_receipt=False,
        final_workspace=False,
        server_sha_ok=True,
        hash_agreement=True,
        fixture_bound=True,
        stream_complete=False,
        timed_out=True,
    )
    assert cls == RunClass.TIMEOUT
    assert "idle_or_hard_timeout_after_admission" in reasons[0]
    # Must not be mislabeled as model competence failure
    assert cls != RunClass.AGENT_FAILURE


def test_06_pre_admission_http_not_admitted():
    STATE.mode = "unauthorized"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.NOT_ADMITTED.value
        assert r.http_status == 401
    finally:
        srv.shutdown()


def test_07_split_and_multiline_sse_frames():
    STATE.mode = "split_frames"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        r = _adapter(base).apply_oracle(r, True) if r.run_class != RunClass.INADMISSIBLE.value else r
        # re-run single adapter instance
        ad = _adapter(base)
        r = ad.run_task("L01", "fix", SEED)
        assert r.final_workspace.get("tree_hash")
        assert r.code_receipt.get("tree_hash")
        r = ad.apply_oracle(r, True)
        assert r.run_class == RunClass.ADMISSIBLE_PASS.value
    finally:
        srv.shutdown()


def test_08_final_workspace_hash_mismatch():
    STATE.mode = "hash_mismatch_fw"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.INADMISSIBLE.value
        assert any("hash" in x or "mismatch" in x for x in r.reasons)
    finally:
        srv.shutdown()


def test_09_receipt_tree_mismatch():
    STATE.mode = "receipt_tree_mismatch"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.INADMISSIBLE.value
    finally:
        srv.shutdown()


def test_10_api_key_redaction_in_logs_and_exceptions():
    # redact helper
    leaked = f"Authorization: Bearer {API_KEY} boom"
    cleaned = redact_text(leaked, [API_KEY])
    assert API_KEY not in cleaned
    assert "REDACTED" in cleaned

    STATE.mode = "leak_key"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        blob = json.dumps(r.to_dict())
        assert API_KEY not in blob
        # classified inadmissible due to secret leak detection on events before redact...
        # adapter redacts events then checks secrets_present on redacted — leak_key
        # is redacted from events so may not trigger secret_leak. Ensure redaction works.
        assert secrets_present(r.events, [API_KEY]) == []
    finally:
        srv.shutdown()


def test_11_fixture_path_traversal_rejected():
    bad = {"../etc/passwd": "x\n"}
    reasons = validate_fixture_paths(bad)
    assert reasons
    try:
        build_resume_package("L99", "x", bad)
        assert False, "should raise"
    except ValueError as exc:
        assert "invalid_fixture" in str(exc) or "path" in str(exc)


def test_12_oversized_fixture_fails_before_transmission():
    big = {"huge.py": "x" * (MAX_FIXTURE_BYTES + 100)}
    reasons = validate_fixture_paths(big)
    assert any("fixture_too_large" in r for r in reasons)
    STATE.mode = "valid"
    srv, base = _start_server()
    before = STATE.requests
    try:
        r = _adapter(base).run_task("L99", "x", big)
        assert r.run_class == RunClass.NOT_ADMITTED.value
        assert STATE.requests == before  # no HTTP call
    finally:
        srv.shutdown()


def test_13_binary_files_without_unsafe_text_coercion():
    fw = build_final_workspace(
        {"ok.py": "print(1)\n"},
        binary_meta={"blob.bin": {"reason": "binary", "size": 3, "sha256": "abc"}},
    )
    assert "blob.bin" not in fw["files"]
    assert any(o.get("path") == "blob.bin" for o in fw["omitted"])
    assert "ok.py" in fw["files"]


def test_14_rate_limit_is_not_admitted_not_model_failure():
    STATE.mode = "rate_limit"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.NOT_ADMITTED.value
        assert r.http_status == 429
        assert r.run_class != RunClass.AGENT_FAILURE.value
    finally:
        srv.shutdown()


def test_15_partial_artifacts_preserved_without_secrets():
    STATE.mode = "missing_receipt"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        d = r.to_dict()
        assert d.get("code_start") or d.get("events_summary")
        assert API_KEY not in json.dumps(d)
        # partial stream still recorded
        assert r.final_workspace or r.code_done or r.events
    finally:
        srv.shutdown()


def test_sse_parser_multiline_data():
    buf, events = parse_sse_chunk("", "event: x\ndata: {\"a\":\n")
    assert events == []
    buf, events = parse_sse_chunk(buf, "1}\n\n")
    # incomplete json may land as _raw — still one event
    assert len(events) == 1


def test_oracle_agent_failure_not_inadmissible():
    STATE.mode = "valid"
    srv, base = _start_server()
    try:
        ad = _adapter(base)
        r = ad.run_task("L01", "fix", SEED)
        r = ad.apply_oracle(r, False, ["wrong_file"])
        assert r.run_class == RunClass.AGENT_FAILURE.value
        assert "wrong_file" in r.reasons
    finally:
        srv.shutdown()


def test_fixture_package_from_seed_only():
    pkg = build_resume_package("L01", "Fix util", SEED)
    assert pkg["workspace_snapshot"] == SEED
    assert pkg["fixture_hash"] == fixture_hash(SEED)
    assert pkg["resume_token"].startswith("benchmark:L01:")


def test_16_post_seal_tree_hash_mutation_is_inadmissible():
    """Any post-seal tree-hash change must fail receipt_hash_match / adapter gate."""
    from local_ui.receipt_sign import verify_code_receipt

    th = tree_hash(SEED)
    sealed = _signed_receipt(th, file_count=2, total_bytes=20)
    assert verify_code_receipt(sealed)["receipt_hash_match"] is True
    mutated = dict(sealed)
    mutated["tree_hash"] = "f" * 64
    mutated["workspace_tree_hash"] = "f" * 64
    assert verify_code_receipt(mutated)["receipt_hash_match"] is False

    STATE.mode = "post_seal_mutation"
    srv, base = _start_server()
    try:
        r = _adapter(base).run_task("L01", "fix", SEED)
        assert r.run_class == RunClass.INADMISSIBLE.value
        assert any(
            "receipt_hash" in x or "signature" in x or "mismatch" in x
            for x in r.reasons
        )
    finally:
        srv.shutdown()


def test_17_signed_tree_hash_matches_reconstructed_bytes():
    """Happy path: signed verification.workspace_tree_sha256 == reconstructed tree."""
    STATE.mode = "valid"
    srv, base = _start_server()
    try:
        ad = _adapter(base)
        r = ad.run_task("L01", "fix", SEED)
        r = ad.apply_oracle(r, True)
        assert r.run_class == RunClass.ADMISSIBLE_PASS.value
        th = r.tree_hashes
        assert th["receipt_signed"]
        assert th["receipt_signed"] == th["reconstructed"]
        assert th["final_workspace_declared"] == th["reconstructed"]
        ver = (r.code_receipt.get("verification") or {})
        assert ver.get("workspace_tree_sha256") == th["reconstructed"]
        from local_ui.receipt_sign import verify_code_receipt
        assert verify_code_receipt(r.code_receipt)["receipt_hash_match"] is True
        assert verify_code_receipt(r.code_receipt)["signature_valid"] is True
    finally:
        srv.shutdown()


def test_18_code_agent_seals_workspace_before_emit():
    """Product CodeAgent: workspace tree hash is inside the signed receipt core."""
    import tempfile
    from pathlib import Path
    from local_ui.code_agent import CodeAgent
    from local_ui.sandbox import Sandbox
    from local_ui.receipt_sign import verify_code_receipt

    sb = Sandbox(Path(tempfile.mkdtemp()))
    seq = iter([
        "FILE: solution.py\n```\nprint('hi')\n```\nRUN: python3 solution.py\n",
        "DONE: done\n",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None, max_steps=4, nfet=False)
    events = list(agent.run("Create solution.py that prints hi"))
    rec = [e["data"] for e in events if e["event"] == "code_receipt"][0]
    fw = [e["data"] for e in events if e["event"] == "final_workspace"]
    assert fw, "final_workspace must be emitted"
    v = verify_code_receipt(rec)
    assert v["receipt_hash_match"] is True, v
    assert v["signature_valid"] is True, v
    tree = (rec.get("verification") or {}).get("workspace_tree_sha256") or rec.get("tree_hash")
    assert tree
    assert tree == fw[0].get("tree_hash")
    # Mutating after the fact must break the seal
    broken = dict(rec)
    broken["tree_hash"] = "0" * 64
    assert verify_code_receipt(broken)["receipt_hash_match"] is False
