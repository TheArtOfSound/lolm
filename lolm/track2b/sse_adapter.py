# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Remote product CodeAgent SSE transport for Track 2B."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from lolm.track2b.classify import RunClass, classify_run
from lolm.track2b.fixtures import build_sse_request, fixture_hash, validate_fixture_paths
from lolm.track2b.redact import redact_secrets, redact_text, secrets_present
from lolm.track2b.sse_parse import parse_sse_chunk
from lolm.track2b.workspace import reconstruct_tree, tree_hash


@dataclass
class SSEAdapterConfig:
    base_url: str
    api_key: str
    expected_server_sha: str
    path: str = "/api/demo/code/run"
    max_steps: int = 28
    idle_timeout_s: float = 180.0
    hard_timeout_s: float = 600.0
    connect_timeout_s: float = 30.0


@dataclass
class SSERunResult:
    transport: str = "lolm-code-sse"
    task_id: str = ""
    run_class: str = RunClass.NOT_ADMITTED.value
    reasons: List[str] = field(default_factory=list)
    admitted: bool = False
    http_status: Optional[int] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    code_start: Dict[str, Any] = field(default_factory=dict)
    code_done: Dict[str, Any] = field(default_factory=dict)
    code_receipt: Dict[str, Any] = field(default_factory=dict)
    final_workspace: Dict[str, Any] = field(default_factory=dict)
    reconstructed_tree: Dict[str, str] = field(default_factory=dict)
    tree_hashes: Dict[str, str] = field(default_factory=dict)
    server_sha: str = ""
    model_id: str = ""
    provider: str = ""
    deployment_id: str = ""
    run_id: str = ""
    fixture_hash: str = ""
    elapsed_s: float = 0.0
    request_meta: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transport": self.transport,
            "task_id": self.task_id,
            "run_class": self.run_class,
            "reasons": list(self.reasons),
            "admitted": self.admitted,
            "http_status": self.http_status,
            "server_sha": self.server_sha,
            "model_id": self.model_id,
            "provider": self.provider,
            "deployment_id": self.deployment_id,
            "run_id": self.run_id,
            "fixture_hash": self.fixture_hash,
            "tree_hashes": self.tree_hashes,
            "elapsed_s": self.elapsed_s,
            "code_start": self.code_start,
            "code_done": self.code_done,
            "code_receipt": self.code_receipt,
            "final_workspace": {
                k: v for k, v in (self.final_workspace or {}).items()
                if k != "files"  # keep lean; full files in reconstructed_tree
            },
            "reconstructed_paths": sorted(self.reconstructed_tree.keys()),
            "events_summary": [
                {"event": e.get("event"), "keys": list((e.get("data") or {}).keys())[:12]}
                for e in self.events
            ][:80],
            "error": self.error,
            "request_meta": self.request_meta,
        }


class LolmCodeSSEAgentAdapter:
    """POST /api/demo/code/run with resume_package fixture; parse SSE stream."""

    TRANSPORT = "lolm-code-sse"

    def __init__(self, config: SSEAdapterConfig) -> None:
        self.config = config
        self._secrets = [config.api_key] if config.api_key else []

    def run_task(
        self,
        task_id: str,
        task_text: str,
        seed_files: Mapping[str, str],
    ) -> SSERunResult:
        t0 = time.time()
        result = SSERunResult(task_id=task_id, transport=self.TRANSPORT)

        # Preflight fixture
        path_errs = validate_fixture_paths(seed_files)
        if path_errs:
            result.run_class = RunClass.NOT_ADMITTED.value
            result.reasons = path_errs
            result.error = "fixture_validation_failed"
            result.elapsed_s = round(time.time() - t0, 3)
            return self._redact_result(result)

        fhash = fixture_hash(seed_files)
        result.fixture_hash = fhash
        try:
            body = build_sse_request(
                task_id, task_text, seed_files, max_steps=self.config.max_steps,
            )
        except ValueError as exc:
            result.run_class = RunClass.NOT_ADMITTED.value
            result.reasons = [str(exc)[:200]]
            result.error = "fixture_package_build_failed"
            result.elapsed_s = round(time.time() - t0, 3)
            return self._redact_result(result)

        # Bind check
        pkg = body.get("resume_package") or {}
        if pkg.get("fixture_hash") != fhash:
            result.run_class = RunClass.INADMISSIBLE.value
            result.reasons = ["fixture_package_unbound"]
            result.elapsed_s = round(time.time() - t0, 3)
            return self._redact_result(result)

        result.request_meta = {
            "session_id": body.get("session_id"),
            "conversation_id": body.get("conversation_id"),
            "max_steps": body.get("max_steps"),
            "resume_token": (pkg.get("resume_token") or "")[:80],
            "fixture_hash": fhash,
            # never include workspace_snapshot body size only
            "workspace_file_count": len(pkg.get("workspace_snapshot") or {}),
        }

        url = self.config.base_url.rstrip("/") + self.config.path
        payload = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-LOLM-Api-Key": self.config.api_key,
            "User-Agent": "lolm-track2b-sse/1",
        }

        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            # Connect timeout only — stream idle/hard timeouts are enforced in the reader loop.
            # Passing hard_timeout here would abort long legitimate runs and hang mocks.
            resp = urllib.request.urlopen(req, timeout=self.config.connect_timeout_s)
        except urllib.error.HTTPError as e:
            result.http_status = e.code
            raw = e.read(500).decode("utf-8", "replace")
            result.error = redact_text(raw, self._secrets)[:300]
            cls, reasons = classify_run(
                http_status=e.code,
                admitted=False,
                pre_admission_error=f"http_{e.code}",
            )
            result.run_class = cls.value
            result.reasons = reasons
            result.elapsed_s = round(time.time() - t0, 3)
            return self._redact_result(result)
        except Exception as exc:
            result.error = redact_text(str(exc), self._secrets)[:300]
            result.run_class = RunClass.NOT_ADMITTED.value
            result.reasons = ["pre_admission_transport_error"]
            result.elapsed_s = round(time.time() - t0, 3)
            return self._redact_result(result)

        result.http_status = getattr(resp, "status", 200)
        result.admitted = True
        buf = ""
        last_byte_at = time.time()
        timed_out = False
        saw_start = saw_done = saw_receipt = saw_fw = False

        # Background reader so idle/hard timeouts work even if resp.read blocks.
        import queue
        import threading

        q: "queue.Queue[Optional[bytes]]" = queue.Queue()
        stop = threading.Event()

        def _reader() -> None:
            # Blocking reads only. Idle detection is queue-side in the main loop.
            # Do NOT set a socket timeout: http.client marks the response unusable
            # after a timeout ("cannot read from timed out object").
            try:
                try:
                    resp.fp.raw._sock.settimeout(None)  # type: ignore[attr-defined]
                except Exception:
                    pass
                while not stop.is_set():
                    try:
                        chunk = resp.read(4096)
                    except Exception:
                        q.put(None)
                        return
                    q.put(chunk)
                    if not chunk:
                        return
            except Exception:
                q.put(None)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        saw_any_event = False
        try:
            while True:
                now = time.time()
                if now - t0 > self.config.hard_timeout_s:
                    timed_out = True
                    break
                remaining = self.config.hard_timeout_s - (now - t0)
                if remaining <= 0:
                    timed_out = True
                    break
                if saw_any_event:
                    wait = min(self.config.idle_timeout_s, remaining)
                else:
                    wait = min(max(self.config.idle_timeout_s, 5.0), 30.0, remaining)
                if saw_any_event and (now - last_byte_at > self.config.idle_timeout_s):
                    timed_out = True
                    break
                try:
                    chunk = q.get(timeout=max(0.05, wait))
                except queue.Empty:
                    timed_out = True
                    break
                if chunk is None or chunk == b"":
                    break
                last_byte_at = time.time()
                saw_any_event = True
                buf, events = parse_sse_chunk(buf, chunk.decode("utf-8", errors="replace"))
                for ev in events:
                    if secrets_present(ev, self._secrets):
                        result.error = ((result.error or "") + ";secret_in_stream").strip(";")
                    clean = redact_secrets(ev, self._secrets)
                    result.events.append(clean)
                    name = clean.get("event") or ""
                    data = clean.get("data") or {}
                    if name == "code_start":
                        saw_start = True
                        result.code_start = data
                        self._pull_identity(result, data)
                    elif name == "code_done":
                        saw_done = True
                        result.code_done = data
                        self._pull_identity(result, data)
                    elif name == "code_receipt":
                        saw_receipt = True
                        result.code_receipt = data
                        self._pull_identity(result, data)
                    elif name == "final_workspace":
                        saw_fw = True
                        result.final_workspace = data
                    elif name == "error":
                        result.error = str(data.get("error") or data)[:300]
        except Exception as exc:
            msg = str(exc)
            if "timed out" in msg.lower() or "timeout" in type(exc).__name__.lower():
                timed_out = True
            else:
                result.error = redact_text(msg, self._secrets)[:300]
                if not saw_start:
                    result.admitted = False
        finally:
            stop.set()
            try:
                resp.close()
            except Exception:
                pass

        # Reconstruct + hash agreement
        tree, computed_hash, fw_errs = reconstruct_tree(result.final_workspace)
        result.reconstructed_tree = tree
        receipt_hash = (
            (result.code_receipt.get("tree_hash")
             or result.code_receipt.get("workspace_tree_hash")
             or (result.code_receipt.get("mutation_gateway") or {}).get("tree_hash")
             or "")
        )
        fw_declared = result.final_workspace.get("tree_hash") or ""
        result.tree_hashes = {
            "final_workspace_declared": fw_declared,
            "reconstructed": computed_hash,
            "receipt": str(receipt_hash or ""),
        }
        hash_ok = bool(fw_declared) and fw_declared == computed_hash
        if receipt_hash:
            hash_ok = hash_ok and str(receipt_hash) == computed_hash
        else:
            # receipt may omit tree_hash on older servers — require final_workspace only
            # but staging mandate says all three must agree; missing receipt hash = fail
            hash_ok = False
            fw_errs.append("receipt_tree_hash_absent")

        secret_leak = ";secret_in_stream" in (result.error or "")
        # Post-redact check: redacted artifacts must not retain the raw key
        if secrets_present(result.events, self._secrets) or secrets_present(
            result.to_dict(), self._secrets
        ):
            secret_leak = True

        fixture_bound = (
            (result.code_start.get("fixture_hash") in (None, "", fhash)
             or result.code_start.get("fixture_hash") == fhash)
            and fhash == result.fixture_hash
        )
        # Prefer explicit binding when server echoes fixture_hash
        if result.code_start.get("fixture_hash") and result.code_start.get("fixture_hash") != fhash:
            fixture_bound = False

        server_sha_ok = (
            bool(result.server_sha)
            and result.server_sha == self.config.expected_server_sha
        )
        # Also accept identity on any of the three events
        for blob in (result.code_start, result.code_done, result.code_receipt):
            if blob.get("server_sha") == self.config.expected_server_sha:
                server_sha_ok = True
                result.server_sha = blob.get("server_sha") or result.server_sha

        stream_complete = saw_done and saw_receipt and saw_fw and not timed_out

        cls, reasons = classify_run(
            http_status=result.http_status,
            admitted=result.admitted and saw_start,
            code_start=saw_start,
            code_done=saw_done,
            code_receipt=saw_receipt,
            final_workspace=saw_fw,
            server_sha_ok=server_sha_ok,
            hash_agreement=hash_ok and not fw_errs,
            fixture_bound=fixture_bound,
            stream_complete=stream_complete,
            secret_leak=secret_leak,
            oracle_ok=None,  # filled by harness
            timed_out=timed_out,
        )
        if fw_errs and cls == RunClass.ADMISSIBLE_PASS:
            cls = RunClass.INADMISSIBLE
            reasons = list(fw_errs)
        result.run_class = cls.value
        result.reasons = list(dict.fromkeys(list(reasons) + fw_errs))
        result.elapsed_s = round(time.time() - t0, 3)
        return self._redact_result(result)

    def _pull_identity(self, result: SSERunResult, data: Dict[str, Any]) -> None:
        for key, attr in (
            ("server_sha", "server_sha"),
            ("model_id", "model_id"),
            ("provider", "provider"),
            ("deployment_id", "deployment_id"),
            ("run_id", "run_id"),
        ):
            val = data.get(key)
            if val and not getattr(result, attr):
                setattr(result, attr, str(val))

    def _redact_result(self, result: SSERunResult) -> SSERunResult:
        result.error = redact_text(result.error, self._secrets)
        result.events = redact_secrets(result.events, self._secrets)  # type: ignore[assignment]
        result.code_start = redact_secrets(result.code_start, self._secrets)
        result.code_done = redact_secrets(result.code_done, self._secrets)
        result.code_receipt = redact_secrets(result.code_receipt, self._secrets)
        result.final_workspace = redact_secrets(result.final_workspace, self._secrets)
        return result

    def apply_oracle(
        self,
        result: SSERunResult,
        oracle_ok: bool,
        oracle_notes: Optional[Sequence[str]] = None,
    ) -> SSERunResult:
        """Attach independent oracle after admission; never upgrades inadmissible."""
        if result.run_class in (
            RunClass.INADMISSIBLE.value,
            RunClass.NOT_ADMITTED.value,
            RunClass.TIMEOUT.value,
        ):
            if oracle_notes:
                result.reasons = list(result.reasons) + [f"oracle_note:{n}" for n in oracle_notes[:5]]
            return result
        if result.run_class not in (
            RunClass.ADMITTED.value,
            RunClass.ADMISSIBLE_PASS.value,
            RunClass.AGENT_FAILURE.value,
        ):
            return result
        if oracle_ok:
            result.run_class = RunClass.ADMISSIBLE_PASS.value
            result.reasons = []
        else:
            result.run_class = RunClass.AGENT_FAILURE.value
            result.reasons = list(oracle_notes or ["oracle_failed"])
        return result
