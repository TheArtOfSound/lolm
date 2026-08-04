# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Usage limits + paid monthly tiers, done honestly and cheaply.

Pricing beats the big assistants ($20/mo) while every serving cost here is
near-zero (free-tier cascade providers + the box), so paid tiers are ~pure
margin:

    free   $0      — try it every day
    plus   $7.99   — everyday use
    pro    $19.99  — heavy use + priority ensemble builds

Mechanics (stdlib + the existing Stripe pattern, no webhooks needed):
  - IDENTITY: an anonymous visitor is `ip:<addr>`; a subscriber carries a SIGNED
    license token (HMAC, no server session store); the owner carries a SIGNED
    admin token minted by the shield (password checked as SHA-256 vs
    LOLM_ADMIN_PASS_SHA256 — plaintext is never stored anywhere).
  - COUNTERS: per-day JSON file under runs/usage/ (thread-locked). Limits reset
    at UTC midnight by filename.
  - SUBSCRIBE: Stripe hosted Checkout (mode=subscription, inline price_data).
    On success Stripe redirects back with the session id; /api/billing/claim
    verifies the session + subscription state with Stripe and mints the license
    token. Tokens expire in ~5 weeks; refresh re-verifies the subscription, so a
    cancelled card stops working within a billing cycle without webhooks.

Local/sovereign installs are never limited: when no admin hash is configured
(i.e. not the shared box), everything is unlimited by default.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

TIERS: Dict[str, Dict[str, Any]] = {
    "free": {"label": "Free",  "usd": 0.0,   "runs_per_day": 10,   "visual_per_day": 3},
    "plus": {"label": "Plus",  "usd": 7.99,  "runs_per_day": 300,  "visual_per_day": 30},
    "pro":  {"label": "Pro",   "usd": 19.99, "runs_per_day": 2000, "visual_per_day": 200},
}

_LOCK = threading.Lock()
_USAGE_DIR: Optional[Path] = None


def init(root: Path) -> None:
    global _USAGE_DIR
    _USAGE_DIR = Path(root) / "usage"
    _USAGE_DIR.mkdir(parents=True, exist_ok=True)


def enforced() -> bool:
    """Limits apply only where an admin hash is configured (the shared box).
    A local/sovereign install without one is always unlimited."""
    return bool(os.environ.get("LOLM_ADMIN_PASS_SHA256", "").strip())


# ── signing ──────────────────────────────────────────────────────────────────

def _signing_secret() -> bytes:
    s = os.environ.get("LOLM_SIGNING_SECRET", "").strip()
    if s:
        return s.encode()
    # stable fallback so tokens survive restarts even if only the hash is set
    return ("lolm-sign:" + os.environ.get("LOLM_ADMIN_PASS_SHA256", "dev")).encode()


def _sign(payload: str) -> str:
    mac = hmac.new(_signing_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}|{mac}"


def _verify(token: str) -> Optional[str]:
    if not token or "|" not in token:
        return None
    payload, mac = token.rsplit("|", 1)
    good = hmac.new(_signing_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, good):
        return None
    return payload


# ── admin (the shield) ──────────────────────────────────────────────────────

def admin_unlock(password: str) -> Optional[str]:
    """Password → 30-day signed admin token. Compared as SHA-256 against
    LOLM_ADMIN_PASS_SHA256; the plaintext never touches disk or logs."""
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


# ── licenses (subscribers) ──────────────────────────────────────────────────

def mint_license(sub_id: str, tier: str, days: int = 35) -> str:
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


# ── counting + the gate ─────────────────────────────────────────────────────

def _day_file() -> Path:
    assert _USAGE_DIR is not None, "usage_limits.init(root) not called"
    return _USAGE_DIR / time.strftime("usage-%Y%m%d.json", time.gmtime())


def _bump(identity: str, kind: str) -> int:
    with _LOCK:
        f = _day_file()
        data: Dict[str, Dict[str, int]] = {}
        if f.exists():
            try:
                data = json.loads(f.read_text() or "{}")
            except Exception:
                data = {}
        row = data.setdefault(identity, {})
        row[kind] = int(row.get(kind, 0)) + 1
        f.write_text(json.dumps(data))
        return row[kind]


def _used(identity: str, kind: str) -> int:
    f = _day_file()
    if not f.exists():
        return 0
    try:
        return int((json.loads(f.read_text() or "{}").get(identity) or {}).get(kind, 0))
    except Exception:
        return 0


def _identity_and_tier(request: Any) -> Dict[str, Any]:
    """Resolve who is calling and which tier they are on — no counters touched.

    Returns keys: tier, identity, admin, unlimited (bool). unlimited covers
    local installs, loopback, and the owner shield.

    Priority: admin shield → product API key → signed license → IP.
    API keys beat IP so a browser-minted principal owns its own quota/conversations
    even when behind a shared egress IP.
    """
    if not enforced():
        return {"tier": "unlimited", "identity": "local", "admin": False, "unlimited": True}
    headers = getattr(request, "headers", {}) or {}
    client = getattr(request, "client", None)
    # the machine itself (no proxy header + loopback client) is never limited:
    # the box's own eval scripts and a local Mac app must keep working
    if not headers.get("x-forwarded-for") and getattr(client, "host", "") in ("127.0.0.1", "::1"):
        return {"tier": "unlimited", "identity": "loopback", "admin": False, "unlimited": True}
    if is_admin(headers.get("x-lolm-admin", "")):
        return {"tier": "admin", "identity": "admin", "admin": True, "unlimited": True}
    # Product API key (X-LOLM-Api-Key) — immutable principal, tier from key row.
    try:
        from local_ui import api_keys
        token = api_keys.extract_api_key(headers)
        row = api_keys.read_api_key(token) if token else None
    except Exception:
        row = None
    if row:
        tier = (row.get("tier") or "free").strip().lower()
        if tier not in TIERS:
            tier = "free"
        return {
            "tier": tier,
            "identity": f"api:{row.get('key_id')}",
            "admin": False,
            "unlimited": False,
            "sub_id": row.get("sub_id") or "",
            "key_id": row.get("key_id"),
        }
    lic = read_license(headers.get("x-lolm-license", ""))
    tier = lic["tier"] if lic else "free"
    identity = f"sub:{lic['sub_id']}" if lic else f"ip:{_client_ip(request)}"
    return {"tier": tier, "identity": identity, "admin": False, "unlimited": False,
            "sub_id": (lic or {}).get("sub_id")}


def _limit_for(tier: str, kind: str) -> int:
    limit_key = "visual_per_day" if kind == "visual" else "runs_per_day"
    return int(os.environ.get(f"LOLM_{tier.upper()}_{limit_key.upper()}",
                              TIERS[tier][limit_key]))


def usage_status(request: Any) -> Dict[str, Any]:
    """Peek remaining daily budget WITHOUT consuming a unit.

    Used by the workspace chip, pricing page, and any client that needs to
    show "X runs left today" before the next gated call. Safe to poll.
    """
    who = _identity_and_tier(request)
    if who["unlimited"]:
        return {
            "enforced": enforced(),
            "tier": who["tier"],
            "label": "Admin" if who["admin"] else "Unlimited",
            "admin": who["admin"],
            "unlimited": True,
            "runs": {"used": 0, "limit": None, "remaining": None},
            "visual": {"used": 0, "limit": None, "remaining": None},
            "upgrade_hint": False,
            "tiers": public_tiers(),
        }
    tier = who["tier"]
    identity = who["identity"]
    runs_used = _used(identity, "runs")
    visual_used = _used(identity, "visual")
    runs_limit = _limit_for(tier, "runs")
    visual_limit = _limit_for(tier, "visual")
    runs_rem = max(0, runs_limit - runs_used)
    visual_rem = max(0, visual_limit - visual_used)
    return {
        "enforced": True,
        "tier": tier,
        "label": TIERS[tier]["label"],
        "admin": False,
        "unlimited": False,
        "runs": {"used": runs_used, "limit": runs_limit, "remaining": runs_rem},
        "visual": {"used": visual_used, "limit": visual_limit, "remaining": visual_rem},
        # nudge free users when they've burned most of the day budget
        "upgrade_hint": tier == "free" and (runs_rem <= 3 or visual_rem <= 1),
        "tiers": public_tiers(),
    }


def check_request(request: Any, kind: str = "runs") -> Dict[str, Any]:
    """The gate. kind: 'runs' (chat/agent turns) or 'visual' (builds).
    Returns {allowed, tier, used, limit, admin} — and COUNTS the use when allowed.
    Never limits when enforcement is off (local installs) or for the admin."""
    who = _identity_and_tier(request)
    if who["unlimited"]:
        return {"allowed": True, "tier": who["tier"], "admin": who["admin"]}
    tier = who["tier"]
    identity = who["identity"]
    limit = _limit_for(tier, kind)
    used = _used(identity, kind)
    if used >= limit:
        return {"allowed": False, "tier": tier, "used": used, "limit": limit,
                "remaining": 0, "admin": False,
                "error": (f"daily {kind} limit reached ({limit}/{TIERS[tier]['label']}). "
                          "Upgrade for more — cheaper than any big assistant."),
                "tiers": public_tiers()}
    new_used = _bump(identity, kind)
    return {"allowed": True, "tier": tier, "used": new_used, "limit": limit,
            "remaining": max(0, limit - new_used), "admin": False}


def _client_ip(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    fwd = headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", "?") or "?"


def public_tiers() -> Dict[str, Any]:
    return {k: {"label": v["label"], "usd": v["usd"], "runs_per_day": v["runs_per_day"],
                "visual_per_day": v["visual_per_day"]} for k, v in TIERS.items()}


# ── Stripe subscription checkout + claim (no webhooks) ─────────────────────

_STRIPE_SESSIONS = "https://api.stripe.com/v1/checkout/sessions"


def _stripe_key() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def create_subscription_checkout(tier: str, base_url: str) -> Dict[str, Any]:
    import requests
    sk = _stripe_key()
    if not sk:
        return {"error": "billing isn't configured on this instance"}
    if tier not in TIERS or TIERS[tier]["usd"] <= 0:
        return {"error": "unknown tier"}
    t = TIERS[tier]
    base = base_url.rstrip("/")
    data = {
        "mode": "subscription",
        # Land on pricing so the claim banner + "open workspace" CTA are obvious.
        "success_url": f"{base}/pricing.html?sub_session={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/pricing.html?cancelled=1",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(int(round(t["usd"] * 100))),
        "line_items[0][price_data][recurring][interval]": "month",
        "line_items[0][price_data][product_data][name]": f"LOLM {t['label']}",
        "line_items[0][price_data][product_data][description]":
            f"{t['runs_per_day']} runs + {t['visual_per_day']} verified builds per day",
        "subscription_data[metadata][tier]": tier,
        "subscription_data[description]": f"LOLM {t['label']} subscription",
    }
    try:
        r = requests.post(_STRIPE_SESSIONS, data=data, auth=(sk, ""), timeout=15)
        j = r.json()
    except Exception as exc:
        return {"error": f"could not reach Stripe: {str(exc)[:120]}"}
    if r.status_code >= 400:
        return {"error": (j.get("error") or {}).get("message", "Stripe rejected the request")}
    return {"url": j.get("url"), "tier": tier}


def claim_subscription(session_id: str) -> Dict[str, Any]:
    """After the Stripe redirect: verify the checkout session really paid and the
    subscription is live, then mint the signed license token."""
    import requests
    sk = _stripe_key()
    if not sk or not session_id:
        return {"error": "billing isn't configured"}
    try:
        r = requests.get(f"{_STRIPE_SESSIONS}/{session_id}",
                         params={"expand[]": "subscription"}, auth=(sk, ""), timeout=15)
        j = r.json()
    except Exception as exc:
        return {"error": f"could not reach Stripe: {str(exc)[:120]}"}
    if r.status_code >= 400:
        return {"error": (j.get("error") or {}).get("message", "unknown session")}
    sub = j.get("subscription") or {}
    sub_id = sub.get("id") or (j.get("subscription") if isinstance(j.get("subscription"), str) else "")
    status = sub.get("status", "")
    tier = ((sub.get("metadata") or {}).get("tier") or "").strip()
    if j.get("payment_status") not in ("paid", "no_payment_required"):
        return {"error": "checkout not completed"}
    if status not in ("active", "trialing") or tier not in TIERS:
        return {"error": f"subscription not active ({status or 'missing'})"}
    return {"license": mint_license(sub_id, tier), "tier": tier,
            "label": TIERS[tier]["label"]}
