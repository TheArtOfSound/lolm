# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Outbound webhooks for integrate-anywhere (code run complete).

SSRF-hardened: only public http(s) hosts, no link-local / private ranges.
Fire-and-forget with short timeout — never blocks the agent stream.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse


def _is_public_host(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip_s = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_s)
        except ValueError:
            return False
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return False
    return True


def validate_webhook_url(url: str) -> Optional[str]:
    """Return error string or None if OK."""
    u = (url or "").strip()
    if not u:
        return None
    if len(u) > 500:
        return "webhook_url too long"
    try:
        p = urlparse(u)
    except Exception:
        return "invalid webhook_url"
    if p.scheme not in ("http", "https"):
        return "webhook_url must be http(s)"
    if not p.hostname or not _is_public_host(p.hostname):
        return "webhook_url host must be public (SSRF guard)"
    return None


def fire_webhook(url: str, payload: Dict[str, Any], *, timeout: float = 8.0) -> None:
    """POST JSON in a daemon thread. Never raises to caller."""
    err = validate_webhook_url(url)
    if err or not url:
        return

    def _run() -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url.strip(),
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "LOLM-Webhook/1.0",
                    "X-LOLM-Event": str(payload.get("event") or "code.run.completed"),
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read(4096)
        except Exception:
            pass

    threading.Thread(target=_run, name="lolm-webhook", daemon=True).start()
