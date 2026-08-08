# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Retired hosted-integration compatibility routes.

GET /api/demo/integrate
  Returns the local CLI integration contract. Public execution is disabled by
  the server boundary in ``server_public_demo.py``.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from local_ui import usage_limits

PUBLIC_BASE = "https://lolm.imagineqira.com"


class KeyCreate(BaseModel):
    tier: str = "free"
    label: str = "default"


class KeyRevoke(BaseModel):
    key_id: str

# Documentation-only contract. Historical route implementations below stay
# importable for private self-host tests but are blocked on the public surface.
INTEGRATION_CATALOG: Dict[str, Any] = {
    "product": "LOLM",
    "version": "cli-only-v2",
    "hosted_execution": False,
    "install": "npm install -g lolm-cli",
    "auth": {"model_provider": "Bring your own provider key with lolm setup"},
    "clients": {
        "cli": "lolm-cli (bin: lolm)",
    },
    "endpoints": [],
    "examples": {
        "docs": f"{PUBLIC_BASE}/developers.html",
        "cli": "npm install -g lolm-cli && lolm code \"build fizzbuzz to 20\"",
    },
}


def register_integrate_routes(app: Any) -> None:
    @app.get("/api/demo/integrate")
    def integrate_catalog():
        cat = dict(INTEGRATION_CATALOG)
        return cat

    @app.get("/api/demo/integrate/openapi.json")
    def integrate_openapi_lite():
        """Minimal OpenAPI 3 stub so tools can discover public demo routes."""
        paths = {}
        for ep in INTEGRATION_CATALOG["endpoints"]:
            method = ep["method"].lower()
            path = ep["path"].split("?")[0]
            paths.setdefault(path, {})[method] = {
                "summary": ep.get("purpose", ""),
                "operationId": ep.get("id"),
                "responses": {"200": {"description": "OK"}},
            }
        return {
            "openapi": "3.0.3",
            "info": {
                "title": "LOLM CLI integration notice",
                "version": "2.0.0",
                "description": (
                    "Public hosted execution is retired. Install the local LOLM CLI. "
                    "Guide: https://lolm.imagineqira.com/install.html"
                ),
            },
            "servers": [{"url": PUBLIC_BASE}],
            "paths": paths,
        }

    @app.post("/api/demo/api-keys")
    def create_api_key(body: KeyCreate, request: Request):
        """Mint a LOLM product API key (X-LOLM-Api-Key) — not provider BYOK keys."""
        from local_ui import api_keys
        from local_ui.usage_limits import TIERS, _client_ip, _identity_and_tier
        tier = (body.tier or "free").strip().lower()
        if tier not in TIERS:
            return JSONResponse({"error": "unknown tier"}, status_code=400)
        who = _identity_and_tier(request)
        # Paid keys require a license at that tier (or higher) or unlimited.
        if tier in ("plus", "pro") and not who.get("unlimited"):
            order = ["free", "plus", "pro"]
            have = who.get("tier") or "free"
            if have not in order or order.index(have) < order.index(tier):
                return JSONResponse(
                    {"error": f"minting {tier} keys requires a {tier}+ license "
                              "(X-LOLM-License) or self-host unlimited"},
                    status_code=402,
                )
        out = api_keys.mint_api_key(
            tier=tier,
            label=body.label or "default",
            sub_id=str(who.get("sub_id") or ""),
            ip=_client_ip(request),
        )
        if out.get("error"):
            return JSONResponse(out, status_code=429 if "rate" in out["error"] else 400)
        return out

    @app.get("/api/demo/api-keys")
    def list_api_keys(request: Request):
        from local_ui import api_keys
        from local_ui.usage_limits import _identity_and_tier
        who = _identity_and_tier(request)
        sub = str(who.get("sub_id") or "")
        kid = who.get("api_key_id")
        rows = api_keys.list_keys_meta(sub_id=sub, include_revoked=False)
        if kid:
            rows = [r for r in rows if r.get("key_id") == kid] or rows
        return {"keys": rows, "tier": who.get("tier")}

    @app.post("/api/demo/api-keys/revoke")
    def revoke_api_key(body: KeyRevoke, request: Request):
        from local_ui import api_keys
        from local_ui.usage_limits import _identity_and_tier
        who = _identity_and_tier(request)
        ok = api_keys.revoke_api_key(
            body.key_id,
            owner_sub=str(who.get("sub_id") or ""),
            require_sub=bool(who.get("sub_id")),
        )
        if not ok:
            return JSONResponse({"error": "key not found or not owned"}, status_code=404)
        return {"revoked": True, "key_id": body.key_id}

    # Backward-compat aliases (mint only when body looks like product key mint)
    @app.post("/api/demo/keys/mint")
    def create_api_key_alias(body: KeyCreate, request: Request):
        return create_api_key(body, request)
