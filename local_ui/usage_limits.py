# Copyright (c) 2026 Qira LLC
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retired hosted-usage compatibility layer.

LOLM is distributed as a local, bring-your-own-key CLI. The public website does
not meter prompts, sell plans, or create payment sessions. These small helpers
remain so older self-hosted integrations and signed commercial entitlements fail
cleanly without reviving hosted execution or public purchasing.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


# Stable legacy identifiers are retained for existing API-key records. They are
# access classes, not public products, quotas, or prices.
TIERS: Dict[str, Dict[str, Any]] = {
    "free": {"label": "Community", "commercial": False},
    "plus": {"label": "Commercial", "commercial": True},
    "pro": {"label": "Commercial Plus", "commercial": True},
}


def init(root: Path) -> None:
    """Compatibility no-op; local CLI execution has no usage counter."""
    Path(root).mkdir(parents=True, exist_ok=True)


def enforced() -> bool:
    """Hosted prompt quotas are permanently disabled."""
    return False


def _signing_secret() -> bytes:
    value = os.environ.get("LOLM_SIGNING_SECRET", "").strip()
    if value:
        return value.encode()
    return ("lolm-sign:" + os.environ.get("LOLM_ADMIN_PASS_SHA256", "dev")).encode()


def _sign(payload: str) -> str:
    mac = hmac.new(_signing_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}|{mac}"


def _verify(token: str) -> Optional[str]:
    if not token or "|" not in token:
        return None
    payload, mac = token.rsplit("|", 1)
    good = hmac.new(_signing_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return payload if hmac.compare_digest(mac, good) else None


def admin_unlock(password: str) -> Optional[str]:
    want = os.environ.get("LOLM_ADMIN_PASS_SHA256", "").strip().lower()
    if not want:
        return None
    got = hashlib.sha256((password or "").encode()).hexdigest()
    if not hmac.compare_digest(got, want):
        return None
    return _sign(f"admin|{int(time.time()) + 30 * 86400}")


def is_admin(token: str) -> bool:
    payload = _verify(token or "")
    if not payload:
        return False
    parts = payload.split("|")
    return len(parts) == 2 and parts[0] == "admin" and time.time() < float(parts[1])


def mint_license(sub_id: str, tier: str, days: int = 35) -> str:
    """Mint a legacy signed entitlement for a separately negotiated license."""
    if tier not in TIERS:
        raise ValueError("unknown access class")
    return _sign(f"lic|{sub_id}|{tier}|{int(time.time()) + days * 86400}")


def read_license(token: str) -> Optional[Dict[str, str]]:
    payload = _verify(token or "")
    if not payload:
        return None
    parts = payload.split("|")
    if len(parts) != 4 or parts[0] != "lic" or parts[2] not in TIERS:
        return None
    if time.time() >= float(parts[3]):
        return None
    return {"sub_id": parts[1], "tier": parts[2]}


def _client_ip(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(getattr(request, "client", None), "host", "?") or "?"


def _identity_and_tier(request: Any) -> Dict[str, Any]:
    headers = getattr(request, "headers", {}) or {}
    if is_admin(headers.get("x-lolm-admin", "")):
        return {"tier": "admin", "identity": "admin", "admin": True,
                "unlimited": True}
    try:
        from local_ui import api_keys
        token = api_keys.extract_api_key(headers)
        row = api_keys.read_api_key(token) if token else None
    except Exception:
        row = None
    if row:
        tier = row.get("tier") if row.get("tier") in TIERS else "free"
        return {"tier": tier, "identity": f"api:{row.get('key_id')}",
                "admin": False, "unlimited": True,
                "sub_id": row.get("sub_id") or "", "key_id": row.get("key_id")}
    entitlement = read_license(headers.get("x-lolm-license", ""))
    if entitlement:
        return {"tier": entitlement["tier"],
                "identity": f"license:{entitlement['sub_id']}", "admin": False,
                "unlimited": True, "sub_id": entitlement["sub_id"]}
    return {"tier": "local", "identity": f"local:{_client_ip(request)}",
            "admin": False, "unlimited": True}


def public_tiers() -> Dict[str, Any]:
    """Return access-class metadata without money, quotas, or purchase links."""
    return {key: dict(value) for key, value in TIERS.items()}


def usage_status(request: Any) -> Dict[str, Any]:
    who = _identity_and_tier(request)
    return {"enforced": False, "tier": who["tier"], "label": "Local unlimited",
            "admin": who["admin"], "unlimited": True, "runs": {"used": 0,
            "limit": None, "remaining": None}, "visual": {"used": 0,
            "limit": None, "remaining": None}, "upgrade_hint": False,
            "tiers": public_tiers(), "hosted_execution": False}


def check_request(request: Any, kind: str = "runs") -> Dict[str, Any]:
    who = _identity_and_tier(request)
    return {"allowed": True, "tier": who["tier"], "admin": who["admin"],
            "unlimited": True, "hosted_execution": False, "kind": kind}
