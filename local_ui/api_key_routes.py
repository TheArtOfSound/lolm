# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Small product API-key surface used by authenticated workspace clients."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class KeyCreate(BaseModel):
    tier: str = "free"
    label: str = "default"


def register_api_key_routes(app: Any) -> None:
    @app.post("/api/demo/api-keys")
    def create_api_key(body: KeyCreate, request: Request):
        from local_ui import api_keys
        from local_ui.usage_limits import TIERS, _client_ip, _identity_and_tier

        tier = (body.tier or "free").strip().lower()
        if tier not in TIERS:
            return JSONResponse({"error": "unknown tier"}, status_code=400)
        principal = _identity_and_tier(request)
        if tier in ("plus", "pro") and not principal.get("unlimited"):
            order = ["free", "plus", "pro"]
            current = principal.get("tier") or "free"
            if current not in order or order.index(current) < order.index(tier):
                return JSONResponse(
                    {"error": f"minting {tier} keys requires a {tier}+ license"},
                    status_code=402,
                )
        result = api_keys.mint_api_key(
            tier=tier,
            label=body.label or "default",
            sub_id=str(principal.get("sub_id") or ""),
            ip=_client_ip(request),
        )
        if result.get("error"):
            status = 429 if "rate" in result["error"] else 400
            return JSONResponse(result, status_code=status)
        return result
