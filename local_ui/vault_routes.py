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

import hashlib
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lolm.qev_vault import VaultError, canonical_json, envelope_id, seal, unseal
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
    """Full sealed run bundle — RAW TRACES, not a summary (complaint #9).

    The audit's sharpest vault risk: "a cryptographic wrapper can make weak
    evidence feel official" — sealing a pretty receipt proves a receipt existed,
    not that the run happened as claimed. So the envelope must carry the raw
    material to reproduce the run: the prompt, the model + run-mode, the
    controller thresholds, EVERY retrieved note, the per-token telemetry stream,
    the draft, the baseline (if any), the measured confidence spans, and the
    verifier/critique results — plus a hash over the raw content so a tampered
    answer/draft/trace is detectable independent of the envelope's own AEAD.
    """
    receipt = run.get("receipt") or {}
    result = run.get("result") or {}
    answer = result.get("response")
    bundle = {
        "kind": "lolm_nfet_agent_run",
        "bundle_schema": "qira.run.bundle.v2",
        "command": run.get("command"),
        "answer": answer,
        "model": {
            "requested": run.get("reasoner"),
            "used": receipt.get("model_used") or result.get("profile"),
            "run_mode": receipt.get("run_mode"),
            "fallback_used": receipt.get("fallback_used"),
        },
        "controller_config": run.get("controller_config"),   # thresholds in force
        "evidence": run.get("evidence"),                      # every retrieved note (raw)
        "retrieval": run.get("retrieval"),                    # note->sentence binding
        "draft": run.get("draft"),                            # working draft pre-finalize
        "timeline": run.get("timeline"),                      # decision/action stream
        "frames": run.get("frames"),                          # per-token telemetry (raw)
        "confidence": run.get("confidence"),                  # measured low-confidence spans
        "base": run.get("base"),                              # baseline output, if a base shot ran
        "counters": run.get("counters"),
        "ended_by": run.get("ended_by"),
        "provenance": run.get("provenance"),
        "proof": run.get("proof"),
        "receipt": receipt,                                   # verifier + critique results
    }
    raw = canonical_json({
        "command": bundle["command"], "answer": answer, "draft": bundle["draft"],
        "timeline": bundle["timeline"], "evidence": bundle["evidence"],
        "frames": bundle["frames"],
    })
    bundle["bundle_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return bundle


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
