#!/usr/bin/env python3
"""Safe browser reader sidecar for LOLM-NFET.

This is the safe subset of the Hellhound browser-sidecar idea: keep a real
Playwright browser warm, navigate to public pages, read visible text, and take
screenshots. It intentionally does not expose form filling, arbitrary JS eval,
credential actions, or stealth mode.
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

_browser = None
_page = None
_pw = None
_headless = False
_lock = threading.Lock()


def ensure_browser() -> None:
    global _browser, _page, _pw
    if _browser is not None:
        return
    from playwright.sync_api import sync_playwright

    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=_headless)
    context = _browser.new_context()
    _page = context.new_page()


def shutdown_browser() -> None:
    global _browser, _page, _pw
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _browser = None
    _page = None
    _pw = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        return

    def respond(self, payload: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            params = json.loads(raw) if raw else {}
        except Exception:
            params = {}

        if path == "/health":
            self.respond({"ok": True, "ready": _browser is not None, "headless": _headless})
            return
        if path == "/shutdown":
            self.respond({"ok": True})
            shutdown_browser()
            threading.Thread(target=lambda: self.server.shutdown(), daemon=True).start()
            return

        with _lock:
            try:
                ensure_browser()
                self.respond({"ok": True, "result": self.dispatch(path, params)})
            except Exception as exc:
                self.respond({"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]})

    def dispatch(self, path: str, params: Dict[str, Any]) -> Any:
        if path == "/navigate":
            url = str(params.get("url", ""))
            wait_until = str(params.get("wait_until", "domcontentloaded"))
            timeout = int(params.get("timeout_ms", 30000))
            _page.goto(url, wait_until=wait_until, timeout=timeout)
            return {"url": _page.url, "title": _page.title()}
        if path == "/text":
            try:
                text = _page.locator("body").inner_text()
            except Exception:
                text = ""
            return {"url": _page.url, "title": _page.title(), "text": (text or "")[:12000]}
        if path == "/screenshot":
            out = str(params.get("path") or "/tmp/lolm-browser-reader.png")
            _page.screenshot(path=out, full_page=bool(params.get("full_page", False)))
            return {"path": out, "url": _page.url, "title": _page.title()}
        if path == "/url":
            return {"url": _page.url, "title": _page.title()}
        raise RuntimeError(f"unknown endpoint {path}")


def main() -> int:
    global _headless
    args = sys.argv[1:]
    port = 0
    while args:
        arg = args.pop(0)
        if arg == "--port":
            port = int(args.pop(0))
        elif arg == "--headless":
            _headless = True
    if port == 0:
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
    print(f"PORT={port}", flush=True)
    server = HTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    finally:
        shutdown_browser()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
