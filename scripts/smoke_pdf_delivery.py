#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Production smoke for the real code-agent PDF artifact path.

Creates a clearly labeled unofficial test PDF, reconstructs exact bytes from the
artifact manifest, verifies the byte hash and PDF header, and requires the sealed
receipt to bind the same manifest. No user data or official credential is used.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, Tuple

TASK = (
    "Create output.pdf using only Python standard library code. The PDF must be a valid "
    "one-page document visibly labeled 'UNOFFICIAL LOLM DELIVERY SELF-TEST'. Write the "
    "binary PDF to output.pdf, print 'PDF_READY output.pdf', and do not create any other "
    "user-facing document."
)


def _events(response: Any) -> Iterator[Tuple[str, Dict[str, Any]]]:
    event = "message"
    data = []
    for raw in response:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data:
                text = "\n".join(data)
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = {"_raw": text[:500]}
                yield event, payload
            event, data = "message", []
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            payload = json.loads("\n".join(data))
        except Exception:
            payload = {"_raw": "\n".join(data)[:500]}
        yield event, payload


def run(base: str, api_key: str = "", timeout: int = 600) -> Dict[str, Any]:
    url = base.rstrip("/") + "/api/demo/code/run"
    body = json.dumps({"task": TASK, "max_steps": 14}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "lolm-pdf-delivery-smoke/1",
    }
    if api_key:
        headers["X-LOLM-Api-Key"] = api_key
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    manifest: Dict[str, Any] = {}
    receipt: Dict[str, Any] = {}
    done: Dict[str, Any] = {}
    errors = []
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"unexpected status {response.status}")
        for name, data in _events(response):
            if name == "artifact_manifest":
                manifest = data
            elif name == "code_receipt":
                receipt = data
            elif name == "code_done":
                done = data
            elif name == "error":
                errors.append(data.get("error") or data)

    if errors:
        raise AssertionError(f"stream error: {errors[-1]}")
    if manifest.get("schema") != "lolm.artifact.manifest.v1":
        raise AssertionError("artifact manifest missing")
    if manifest.get("complete") is not True:
        raise AssertionError("artifact manifest incomplete")
    rows = {row.get("path"): row for row in manifest.get("files") or []}
    pdf = rows.get("output.pdf")
    if not pdf:
        raise AssertionError(f"output.pdf absent; paths={sorted(p for p in rows if p)}")
    if pdf.get("encoding") != "base64" or not pdf.get("content_base64"):
        raise AssertionError("output.pdf exact binary body not embedded as base64")
    raw = base64.b64decode(pdf["content_base64"], validate=True)
    if not raw.startswith(b"%PDF-"):
        raise AssertionError("output.pdf does not have a PDF header")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pdf.get("sha256"):
        raise AssertionError("output.pdf SHA-256 mismatch")
    if len(raw) != int(pdf.get("size") or -1):
        raise AssertionError("output.pdf byte count mismatch")
    verification = receipt.get("verification") or {}
    if receipt.get("ok") is not True or receipt.get("verdict") != "shipped":
        raise AssertionError(f"receipt did not ship: {receipt.get('verdict')}")
    if verification.get("artifact_manifest_ok") is not True:
        raise AssertionError("receipt does not approve artifact manifest")
    if verification.get("artifact_manifest_sha256") != manifest.get("manifest_sha256"):
        raise AssertionError("receipt/manifest binding mismatch")
    if done.get("run_id") != receipt.get("run_id"):
        raise AssertionError("code_done/receipt run ID mismatch")
    if "output.pdf" not in (receipt.get("files") or []):
        raise AssertionError("receipt files omit generated output.pdf")
    return {
        "ok": True,
        "run_id": receipt.get("run_id"),
        "receipt_sha": receipt.get("receipt_sha"),
        "artifact_id": manifest.get("artifact_id"),
        "pdf_sha256": digest,
        "pdf_bytes": len(raw),
        "seconds": round(time.time() - started, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://lolm.imagineqira.com")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    last: Exception | None = None
    for attempt in range(1, max(1, args.attempts) + 1):
        try:
            result = run(args.base, args.api_key, args.timeout)
            print(json.dumps(result, sort_keys=True))
            return 0
        except urllib.error.HTTPError as exc:
            last = exc
            # Rate limit and temporary unavailability are retryable, not a pass.
            if exc.code not in (429, 502, 503, 504) or attempt >= args.attempts:
                break
        except Exception as exc:
            last = exc
            if attempt >= args.attempts:
                break
        time.sleep(min(15 * attempt, 45))
    print(json.dumps({"ok": False, "error": str(last)[:500]}, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
