# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Optional 'Support this project' button — Stripe Checkout, done safely.

The Stripe SECRET key is read from the environment (STRIPE_SECRET_KEY) at request time and
used ONLY to create a hosted Checkout Session server-side. It is never logged, never sent to
the browser, and never embedded in code — the donor pays on Stripe's own page, so LOLM never
touches a card. If STRIPE_SECRET_KEY isn't set the feature is simply OFF (the button hides).

Set it the BYOK way (Keys panel / ~/.lolm/keys.env) or `export STRIPE_SECRET_KEY=sk_…`.
"""
from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

_STRIPE_SESSIONS = "https://api.stripe.com/v1/checkout/sessions"
SUGGESTED_USD = [3, 5, 10, 25]


class _DonateBody(BaseModel):
    amount_usd: float = 5.0


def _secret() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def register_donate_routes(app: Any) -> None:

    @app.get("/api/donate/config")
    def donate_config():
        """Whether donations are enabled — never returns the key, only a boolean + presets."""
        return {"enabled": bool(_secret()), "suggested_usd": SUGGESTED_USD,
                "note": "Donations go straight to the maintainer through Stripe's hosted "
                        "checkout. LOLM never sees your card details."}

    @app.post("/api/donate/checkout")
    def donate_checkout(body: _DonateBody, request: Request):
        sk = _secret()
        if not sk:
            return JSONResponse({"error": "donations aren't configured on this instance"},
                                status_code=503)
        amt = max(1.0, min(float(body.amount_usd or 5.0), 10000.0))   # clamp $1–$10k
        base = str(request.base_url).rstrip("/")
        data = {
            "mode": "payment",
            "success_url": f"{base}/index.html?supported=1",
            "cancel_url": f"{base}/index.html",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": str(int(round(amt * 100))),
            "line_items[0][price_data][product_data][name]": "Support LOLM",
            "line_items[0][price_data][product_data][description]":
                "Keep the sovereign, self-evolving AI alive. Thank you.",
            "submit_type": "donate",
        }
        try:
            # The secret key authenticates the API call (HTTP basic, key as username); it is
            # not placed in any URL, response, or log line.
            r = requests.post(_STRIPE_SESSIONS, data=data, auth=(sk, ""), timeout=15)
            j = r.json()
        except Exception as exc:
            return JSONResponse({"error": f"could not reach Stripe: {str(exc)[:120]}"},
                                status_code=502)
        if r.status_code >= 400:
            msg = (j.get("error") or {}).get("message", "Stripe rejected the request")
            return JSONResponse({"error": msg}, status_code=400)
        return {"url": j.get("url"), "amount_usd": amt}
