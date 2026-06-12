# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Seal/verify endpoints for Qira Agent Vault.

POST /api/demo/vault/seal    — seal the most recent run (or a provided
                               payload) into a BRY-NFET-SX-VAULT-V2 envelope.
POST /api/demo/vault/verify  — open an envelope, report layered integrity.

Paths live under /api/demo/ so the existing nginx proxy exposes them without
config changes. The passphrase is used in memory for one KDF call and never
stored or logged; no envelope is retained server-side. Argon2id at the
official parameters costs ~96 MiB / ~0.5 s per call, so sealing gets its own
small per-IP rate limit independent of the run gate.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lolm.qev_vault import VaultError, envelope_id, seal, unseal
from lolm.run_receipt import mark_sealed, mark_verified

SEALS_PER_HOUR = 6
_KDF_LOCK = threading.Semaphore(2)   # bound concurrent 96MiB KDF calls


class SealRequest(BaseModel):
    passphrase: str
    payload: Optional[Dict[str, Any]] = None   # default: the last run


class VerifyRequest(BaseModel):
    passphrase: str
    envelope: Dict[str, Any]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _run_to_payload(run: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, self-contained vault payload for an agent run."""
    return {
        "kind": "lolm_nfet_agent_run",
        "command": run.get("command"),
        "answer": (run.get("result") or {}).get("response"),
        "profile": run.get("profile"),
        "ended_by": run.get("ended_by"),
        "provenance": run.get("provenance"),
        "timeline": run.get("timeline"),
        "counters": run.get("counters"),
        "proof": run.get("proof"),
        "receipt": run.get("receipt"),
        "reasoner": run.get("reasoner"),
    }


def register_vault_routes(app: Any, agent: Any) -> None:
    history: Dict[str, deque] = defaultdict(deque)

    def _rate_limited(ip: str) -> bool:
        now = time.time()
        window = history[ip]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= SEALS_PER_HOUR:
            return True
        window.append(now)
        return False

    @app.post("/api/demo/vault/seal")
    def vault_seal(req: SealRequest, request: Request):
        if _rate_limited(_client_ip(request)):
            return JSONResponse({"error": f"sealing limited to {SEALS_PER_HOUR}/hour per visitor"},
                                status_code=429)
        payload = req.payload
        if payload is None:
            if not agent.last_run:
                return JSONResponse({"error": "no run to seal yet — run the agent first"},
                                    status_code=404)
            payload = _run_to_payload(agent.last_run)
        try:
            with _KDF_LOCK:
                envelope = seal(payload, req.passphrase)
        except VaultError as exc:
            return JSONResponse({"error": str(exc), "reason": exc.reason}, status_code=400)
        receipt = payload.get("receipt")
        if isinstance(receipt, dict):
            mark_sealed(receipt, envelope_id(envelope))
        return {
            "envelope": envelope,
            "envelope_id": envelope_id(envelope),
            "opens_at": "https://secure.imagineqira.com",
            "limits": "AEAD/hash verify artifact integrity and custody only — "
                      "never the factual correctness of the answer inside.",
        }

    @app.post("/api/demo/vault/verify")
    def vault_verify(req: VerifyRequest, request: Request):
        if _rate_limited(_client_ip(request)):
            return JSONResponse({"error": f"verification limited to {SEALS_PER_HOUR}/hour per visitor"},
                                status_code=429)
        try:
            with _KDF_LOCK:
                inner, integrity = unseal(req.envelope, req.passphrase)
        except VaultError as exc:
            return JSONResponse({"error": str(exc), "reason": exc.reason,
                                 "integrity": {"aead_authenticated": False}},
                                status_code=400)
        receipt = None
        payload = inner.get("payload") or {}
        if isinstance(payload.get("receipt"), dict):
            receipt = mark_verified(payload["receipt"], integrity)
        return {"integrity": integrity, "inner_schema": inner.get("schema"),
                "sealed_at": inner.get("sealed_at"), "payload": payload,
                "receipt": receipt}
