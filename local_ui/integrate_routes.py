# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Public integration catalog — machine-readable map for “integrate anywhere.”

GET /api/demo/integrate
  Returns base URL, auth model, rate limits shape, and the stable public routes
  a third-party app should call (Node, Python, curl, browser).
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

# Stable contract for third parties. Paths under /api/demo/ only (nginx public).
INTEGRATION_CATALOG: Dict[str, Any] = {
    "product": "LOLM",
    "version": "integrate-v1",
    "base_url": PUBLIC_BASE,
    "auth": {
        "free": "none (IP daily quota)",
        "paid": "header X-LOLM-License: <token from Stripe claim>",
        "owner_optional": "header X-Workspace-Owner: <your-user-id> for memory scoping",
        "self_host": "no quotas when LOLM_ADMIN_PASS_SHA256 unset",
    },
    "clients": {
        "npm": "lolm-nfet-client",
        "cli": "lolm-cli (bin: lolm)",
        "http": "any language with fetch/HTTP + SSE parser",
    },
    "billing": {
        "model": "daily_quotas",
        "status": "GET /api/demo/billing/usage",
        "checkout": "POST /api/demo/billing/checkout {tier: plus|pro}",
        "topup_checkout": "POST /api/demo/billing/topup/checkout {pack: runs_50|runs_200|visual_10|bundle_100}",
        "topup_claim": "GET /api/demo/billing/topup/claim?session_id=cs_…",
        "webhook": "POST /api/demo/billing/webhook (Stripe-Signature; credits top-ups)",
        "note": "Daily quotas reset UTC midnight. Top-up packs do not expire at midnight.",
    },
    "endpoints": [
        {
            "id": "status",
            "method": "GET",
            "path": "/api/demo/status",
            "purpose": "Health + readiness",
        },
        {
            "id": "usage",
            "method": "GET",
            "path": "/api/demo/billing/usage",
            "purpose": "Remaining runs/visuals + billing glossary",
        },
        {
            "id": "chat_stream",
            "method": "POST",
            "path": "/api/demo/run/stream",
            "purpose": "SSE agent chat with NFET control events",
            "body": {"command": "string", "history": [], "user_memory": []},
            "client": "runAgent()",
        },
        {
            "id": "code_run",
            "method": "POST",
            "path": "/api/demo/code/run",
            "purpose": "SSE coding agent: jail write→run→fix + receipt",
            "body": {"task": "string", "max_steps": 12, "conversation_id": "optional"},
            "client": "runCode()",
            "consumes": "runs",
        },
        {
            "id": "code_health",
            "method": "GET",
            "path": "/api/demo/code/health",
            "purpose": "Sandbox + receipt ledger health",
        },
        {
            "id": "code_receipts",
            "method": "GET",
            "path": "/api/demo/code/receipts?limit=20",
            "purpose": "Public hash-chained receipt ledger",
            "client": "listCodeReceipts()",
        },
        {
            "id": "visual",
            "method": "POST",
            "path": "/api/demo/code/visual",
            "purpose": "Build self-contained HTML app (browser-verified path)",
            "body": {"task": "string"},
            "client": "buildVisual()",
            "consumes": "visual",
        },
        {
            "id": "task_state",
            "method": "GET",
            "path": "/api/demo/code/task_state?conversation_id=",
            "purpose": "Load persistent z_t task state for multi-session resume",
        },
        {
            "id": "tactics",
            "method": "GET",
            "path": "/api/demo/code/tactics?q=",
            "purpose": "Oort/Flows tactic retrieval for a task",
        },
        {
            "id": "techniques",
            "method": "GET",
            "path": "/api/demo/code/techniques",
            "purpose": "Technique library stats",
        },
    ],
    "sse": {
        "content_type": "text/event-stream",
        "format": "event: <name>\\ndata: <json>\\n\\n",
        "code_events": [
            "code_start", "agent_note", "command_started", "command_finished",
            "code_done", "code_receipt", "error",
        ],
        "chat_events": [
            "token", "decision", "action", "proof", "phase", "error",
        ],
    },
    "examples": {
        "docs": f"{PUBLIC_BASE}/developers.html",
        "cli": "npm install -g lolm-cli && lolm code \"fizzbuzz to 20\" --save ./out",
        "npm": "npm install lolm-nfet-client",
    },
}


def register_integrate_routes(app: Any) -> None:
    @app.get("/api/demo/integrate")
    def integrate_catalog():
        cat = dict(INTEGRATION_CATALOG)
        try:
            cat["tiers"] = usage_limits.public_tiers()
            cat["billing_glossary"] = usage_limits.billing_glossary()
        except Exception:
            pass
        cat["auth"] = {
            **INTEGRATION_CATALOG["auth"],
            "api_key": "header X-LOLM-Api-Key: lolm_<id>_<secret> (or Authorization: Bearer …)",
            "create_key": "POST /api/demo/api-keys  {tier, label}",
            "list_keys": "GET /api/demo/api-keys",
            "byok": "GET|POST /api/demo/keys  (provider keys on self-host / owner)",
            "webhook": "POST /api/demo/code/run  body.webhook_url (public https only)",
            "task_state": "GET /api/demo/code/task_state?conversation_id=… or /task_state/{id}",
            "cli": "lolm doctor | code --save | receipt verify | inspect task",
        }
        cat["clients"] = {
            **INTEGRATION_CATALOG["clients"],
            "python": "pip-installable module clients/python (lolm_client)",
        }
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
        paths["/api/demo/api-keys"] = {
            "post": {"summary": "Mint product API key", "operationId": "createApiKey"},
            "get": {"summary": "List product API key metadata", "operationId": "listApiKeys"},
        }
        paths["/api/demo/keys"] = {
            "get": {"summary": "BYOK provider key status", "operationId": "byokStatus"},
            "post": {"summary": "Set BYOK provider keys (loopback/owner)", "operationId": "byokSet"},
        }
        return {
            "openapi": "3.0.3",
            "info": {
                "title": "LOLM Public Demo API",
                "version": "1.1.0",
                "description": (
                    "Integrate the LOLM agent into any platform via HTTP + SSE. "
                    "Full guide: https://lolm.imagineqira.com/developers.html"
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
