#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Local SHA-pinned Track 2B staging stand-in for product CodeAgent SSE.

NOT production. Use only when remote staging is unavailable:

  LOLM_SERVER_SHA=$(git rev-parse HEAD) \\
  LOLM_STAGING_KEY=local-staging-key \\
  python3 scripts/track2b_local_staging_server.py --port 8765

Then:

  export LOLM_LIVE_TRANSPORT=lolm-code-sse
  export LOLM_LIVE_BASE_URL=http://127.0.0.1:8765
  export LOLM_LIVE_API_KEY=local-staging-key
  export LOLM_EXPECTED_SERVER_SHA=$(git rev-parse HEAD)
  python3 scripts/repo_gauntlet_live_model_phase_a.py --live --transport lolm-code-sse ...

Chat backend:
  * default: weak stub (admission/infrastructure proof; competence expected fail)
  * LOLM_STAGING_CHAT=openai + OPENAI_* for real model turns through product path

Receipt integrity (local smoke only):
  Server holds LOLM_RECEIPT_SIGNING_KEYS (private).
  Runner holds LOLM_RECEIPT_VERIFY_KEYS (public only).
  For pure local smoke without key pin files, the runner may set
  LOLM_ALLOW_UNTRUSTED_LOCAL_RECEIPTS=1 — never for remote competence campaigns.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ui.code_agent import CodeAgent
from local_ui.sandbox import Sandbox


def _git_sha() -> str:
    return (
        os.environ.get("LOLM_SERVER_SHA")
        or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True).strip()
    )


def _sse(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def _stub_chat(msgs: List[Dict[str, str]]) -> str:
    # Open-ended weak policy: does not solve fixtures — competence must fail honestly.
    # One READ attempt of a common name if present in the workspace listing, else DONE.
    text = "\n".join(str(m.get("content") or "") for m in msgs)
    for name in (
        "util.py", "greet.py", "cfg.py", "a.py", "auth.py", "dep.py",
        "counter.js", "index.html", "good.py", "working.py", "dead.py",
    ):
        if name in text:
            return f"READ: {name}\nDONE: local-staging-stub incomplete\n"
    return "DONE: local-staging-stub incomplete\n"


def _openai_chat() -> Callable[[List[Dict[str, str]]], str]:
    from lolm.track2b.openai_adapter import make_openai_chat
    base = os.environ.get("LOLM_LIVE_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    key = os.environ.get("LOLM_LIVE_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("LOLM_LIVE_MODEL") or os.environ.get("OPENAI_MODEL") or ""
    if not (base and key and model):
        raise SystemExit("LOLM_STAGING_CHAT=openai requires model endpoint + key + model id")
    # Avoid using same env for product base URL — expect OPENAI_* for model
    return make_openai_chat(base, key, model)


class StagingHandler(BaseHTTPRequestHandler):
    server_version = "LOLM-Track2B-LocalStaging/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("staging: " + (fmt % args) + "\n")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/api/demo/code/run":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
            return

        key = self.headers.get("X-LOLM-Api-Key") or ""
        expected = os.environ.get("LOLM_STAGING_KEY") or "local-staging-key"
        if key != expected:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"bad json"}')
            return

        task = (body.get("task") or "").strip()
        if not task:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"empty task"}')
            return

        max_steps = min(max(int(body.get("max_steps") or 16), 1), 28)
        resume = body.get("resume_package") or None
        session_id = body.get("session_id") or ""
        conversation_id = body.get("conversation_id") or ""
        context_reset = bool(body.get("context_reset"))

        sha = _git_sha()
        os.environ["LOLM_SERVER_SHA"] = sha
        os.environ.setdefault("LOLM_MODEL_ID", os.environ.get("LOLM_STAGING_MODEL_ID", "local-staging-stub"))
        os.environ.setdefault("LOLM_MODEL_PROVIDER", "local-staging")
        os.environ.setdefault("LOLM_DEPLOYMENT_ID", f"local-staging-{sha[:12]}")

        chat_fn = self.server.chat_fn  # type: ignore[attr-defined]
        root = self.server.sandbox_root  # type: ignore[attr-defined]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-LOLM-Server-SHA", sha)
        self.end_headers()

        sb = Sandbox(root)
        agent = CodeAgent(
            sb,
            chat_fn,
            max_steps=max_steps,
            isolated=None,  # local staging: no bwrap required
            nfet=False,
            session_id=session_id,
            conversation_id=conversation_id,
            context_reset=context_reset,
            resume_package=resume,
        )
        try:
            for ev in agent.run(task):
                name = ev.get("event") or "message"
                data = dict(ev.get("data") or {})
                # Envelope identity only for non-sealed events. Never mutate
                # code_receipt after Ed25519 seal (breaks receipt_hash_match).
                if name in ("code_start", "code_done", "final_workspace"):
                    for k, envk in (
                        ("server_sha", None),
                        ("model_id", "LOLM_MODEL_ID"),
                        ("provider", "LOLM_MODEL_PROVIDER"),
                        ("deployment_id", "LOLM_DEPLOYMENT_ID"),
                    ):
                        v = sha if k == "server_sha" else os.environ.get(envk or "", "")
                        if v and not data.get(k):
                            data[k] = v
                    if resume and resume.get("fixture_hash") and not data.get("fixture_hash"):
                        data["fixture_hash"] = resume.get("fixture_hash")
                # code_receipt: stream sealed core exactly as signed
                self.wfile.write(_sse(name, data))
                try:
                    self.wfile.flush()
                except Exception:
                    break
        except Exception as exc:
            msg = str(exc)[:200]
            for secret in (expected, os.environ.get("LOLM_LIVE_API_KEY") or ""):
                if secret and len(secret) >= 8 and secret in msg:
                    msg = msg.replace(secret, "***REDACTED***")
            try:
                self.wfile.write(_sse("error", {"error": msg}))
            except Exception:
                pass
        finally:
            try:
                sb.destroy()
            except Exception:
                pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] in ("/health", "/api/demo/status"):
            sha = _git_sha()
            payload = {
                "ok": True,
                "server_sha": sha,
                "deployment_id": os.environ.get("LOLM_DEPLOYMENT_ID", ""),
                "model_id": os.environ.get("LOLM_MODEL_ID", ""),
                "provider": os.environ.get("LOLM_MODEL_PROVIDER", ""),
                "staging": "local",
                "track2b": True,
            }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    sha = _git_sha()
    os.environ["LOLM_SERVER_SHA"] = sha
    os.environ.setdefault("LOLM_STAGING_KEY", "local-staging-key")
    os.environ.setdefault("LOLM_MODEL_ID", "local-staging-stub")
    os.environ.setdefault("LOLM_MODEL_PROVIDER", "local-staging")
    os.environ.setdefault("LOLM_DEPLOYMENT_ID", f"local-staging-{sha[:12]}")

    mode = os.environ.get("LOLM_STAGING_CHAT", "stub").lower()
    chat_fn: Callable[[List[Dict[str, str]]], str]
    if mode == "openai":
        chat_fn = _openai_chat()
    else:
        chat_fn = _stub_chat

    root = tempfile.mkdtemp(prefix="track2b-staging-sandboxes-")
    httpd = ThreadingHTTPServer((args.host, args.port), StagingHandler)
    httpd.chat_fn = chat_fn  # type: ignore[attr-defined]
    httpd.sandbox_root = root  # type: ignore[attr-defined]

    print(
        json.dumps({
            "listening": f"http://{args.host}:{args.port}",
            "server_sha": sha,
            "key_env": "LOLM_STAGING_KEY",
            "chat": mode,
            "sandbox_root": root,
            "note": "local staging only — not production",
        }, indent=2),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
