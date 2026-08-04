# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Minimal Python client for LOLM public API (stdlib only).

    from lolm_client import LOLM
    c = LOLM(api_key="lolm_…")          # or LOLM() for free IP tier
    for ev in c.run_code("print hello from main.py and run it"):
        print(ev["event"], ev.get("data", {})[:1] if False else "")
    done = c.run_code_collect("fizzbuzz to 20")

Env: LOLM_BASE_URL, LOLM_API_KEY, LOLM_LICENSE
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, List, Optional


DEFAULT_BASE = "https://lolm.imagineqira.com"


class LOLMError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class LOLM:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        license: Optional[str] = None,
        owner: Optional[str] = None,
        timeout: float = 600.0,
    ):
        self.base_url = (base_url or os.environ.get("LOLM_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("LOLM_API_KEY", "")
        self.license = license if license is not None else os.environ.get("LOLM_LICENSE", "")
        self.owner = owner or os.environ.get("LOLM_OWNER", "")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
        if self.api_key:
            h["X-LOLM-Api-Key"] = self.api_key
        if self.license:
            h["X-LOLM-License"] = self.license
        if self.owner:
            h["X-Workspace-Owner"] = self.owner
        return h

    def _url(self, path: str) -> str:
        return self.base_url + path

    def get_json(self, path: str) -> Any:
        req = urllib.request.Request(self._url(path), headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 60)) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(body)
            except Exception:
                j = body
            raise LOLMError(f"HTTP {e.code}: {j}", status=e.code, body=j) from e

    def post_json(self, path: str, payload: Dict[str, Any]) -> Any:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 120)) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(body)
            except Exception:
                j = body
            raise LOLMError(f"HTTP {e.code}: {j}", status=e.code, body=j) from e

    def status(self) -> Any:
        return self.get_json("/api/demo/status")

    def usage(self) -> Any:
        return self.get_json("/api/demo/billing/usage")

    def integrate(self) -> Any:
        return self.get_json("/api/demo/integrate")

    def create_key(self, tier: str = "free", label: str = "default") -> Any:
        return self.post_json("/api/demo/api-keys", {"tier": tier, "label": label})

    def list_keys(self) -> Any:
        return self.get_json("/api/demo/api-keys")

    def run_code(
        self,
        task: str,
        *,
        max_steps: Optional[int] = None,
        conversation_id: str = "",
        webhook_url: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield SSE events as {event, data} dicts."""
        payload: Dict[str, Any] = {"task": task}
        if max_steps is not None:
            payload["max_steps"] = max_steps
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if history:
            payload["history"] = history
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url("/api/demo/code/run"), data=data, headers=self._headers(), method="POST"
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(body)
            except Exception:
                j = body
            raise LOLMError(f"HTTP {e.code}: {j}", status=e.code, body=j) from e
        buf = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                event = None
                data_s = None
                for line in block.split("\n"):
                    if line.startswith("event: "):
                        event = line[7:].strip()
                    elif line.startswith("data: "):
                        data_s = line[6:]
                if not event:
                    continue
                try:
                    data_o = json.loads(data_s) if data_s else {}
                except Exception:
                    data_o = data_s
                yield {"event": event, "data": data_o}

    def run_code_collect(self, task: str, **kwargs: Any) -> Dict[str, Any]:
        """Run code agent and return {done, receipt} from the stream."""
        done = None
        receipt = None
        for ev in self.run_code(task, **kwargs):
            if ev["event"] == "code_done":
                done = ev["data"]
            if ev["event"] == "code_receipt":
                receipt = ev["data"]
            if ev["event"] == "error":
                raise LOLMError(str((ev.get("data") or {}).get("error") or "stream error"), body=ev.get("data"))
        return {"done": done, "receipt": receipt}
