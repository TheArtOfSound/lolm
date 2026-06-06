"""Client wrapper for the LOLM-NFET browser reader sidecar."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests


@dataclass
class BrowserReaderHandle:
    port: int
    process: subprocess.Popen

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = requests.post(f"{self.base_url}{path}", json=payload or {}, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "browser reader failed")
        return data.get("result", data)

    def navigate(self, url: str) -> Dict[str, Any]:
        return self.post("/navigate", {"url": url})

    def text(self) -> Dict[str, Any]:
        return self.post("/text")

    def screenshot(self, path: str = "/tmp/lolm-browser-reader.png") -> Dict[str, Any]:
        return self.post("/screenshot", {"path": path})

    def current_url(self) -> Dict[str, Any]:
        return self.post("/url")

    def shutdown(self) -> None:
        try:
            requests.post(f"{self.base_url}/shutdown", json={}, timeout=5)
        finally:
            try:
                self.process.terminate()
            except Exception:
                pass


def launch_browser_reader(headless: bool = False, timeout: float = 20.0) -> BrowserReaderHandle:
    root = Path(__file__).resolve().parents[1]
    script = root / "local_ui" / "browser_reader.py"
    cmd = [sys.executable, str(script)]
    if headless:
        cmd.append("--headless")
    env = os.environ.copy()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    deadline = time.time() + timeout
    port: Optional[int] = None
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line.startswith("PORT="):
            port = int(line.split("=", 1)[1])
            break
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"browser reader exited early: {err}")
    if port is None:
        proc.terminate()
        raise TimeoutError("browser reader did not report a port")
    return BrowserReaderHandle(port=port, process=proc)
