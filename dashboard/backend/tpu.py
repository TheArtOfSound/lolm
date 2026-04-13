"""Google Cloud TPU management — REST API, no gcloud CLI dependency.

Uses OAuth2 access tokens refreshed from a stored refresh token.
This works from any server without interactive gcloud auth.
"""

import asyncio
import json
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from auth import require_auth

router = APIRouter(prefix="/api/tpu", tags=["tpu"], dependencies=[Depends(require_auth)])

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "lolm-tpu-research")
DEFAULT_ZONE = os.environ.get("TPU_ZONE", "us-central2-b")
TPU_API = "https://tpu.googleapis.com/v2"

# OAuth2 token management
_token_cache = {"access_token": "", "expires_at": 0}

# These come from gcloud's ADC — the refresh token is long-lived
OAUTH_CLIENT_ID = os.environ.get("GCP_OAUTH_CLIENT_ID", "32555940559.apps.googleusercontent.com")
OAUTH_CLIENT_SECRET = os.environ.get("GCP_OAUTH_CLIENT_SECRET", "ZmssLNjJy2998hD4CTg2ejr2")
OAUTH_REFRESH_TOKEN = os.environ.get("GCP_OAUTH_REFRESH_TOKEN", "")


async def get_access_token() -> str:
    """Get a fresh access token, refreshing if needed."""
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    if not OAUTH_REFRESH_TOKEN:
        return os.environ.get("GCP_ACCESS_TOKEN", "")

    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "refresh_token": OAUTH_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        })
        if resp.status_code == 200:
            data = resp.json()
            _token_cache["access_token"] = data["access_token"]
            _token_cache["expires_at"] = now + data.get("expires_in", 3600)
            return _token_cache["access_token"]
    return ""


async def tpu_request(method: str, path: str, body: dict = None, timeout: int = 30) -> dict:
    """Make an authenticated request to the TPU API."""
    token = await get_access_token()
    if not token:
        return {"error": "No GCP credentials configured. Set GCP_OAUTH_REFRESH_TOKEN or GCP_ACCESS_TOKEN."}

    url = f"{TPU_API}/{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        if method == "GET":
            resp = await client.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=body or {}, timeout=timeout)
        elif method == "DELETE":
            resp = await client.delete(url, headers=headers, timeout=timeout)
        else:
            return {"error": f"Unknown method {method}"}

        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}


@router.get("/list")
async def list_tpus(zone: str = DEFAULT_ZONE):
    """List all TPU VMs in project/zone."""
    data = await tpu_request("GET", f"projects/{GCP_PROJECT}/locations/{zone}/nodes")
    if "error" in data:
        return {"error": data.get("error"), "tpus": []}

    tpus = []
    for node in data.get("nodes", []):
        name = node.get("name", "").split("/")[-1]
        tpus.append({
            "name": name,
            "state": node.get("state", "UNKNOWN"),
            "health": node.get("health", "UNKNOWN"),
            "acceleratorType": node.get("acceleratorType", "").split("/")[-1],
            "runtimeVersion": node.get("runtimeVersion", ""),
            "networkEndpoints": [{"ipAddress": ep.get("ipAddress", "")}
                                 for ep in node.get("networkEndpoints", [])],
            "schedulingConfig": node.get("schedulingConfig", {}),
            "createTime": node.get("createTime", ""),
        })
    return {"tpus": tpus}


@router.get("/{name}")
async def describe_tpu(name: str, zone: str = DEFAULT_ZONE):
    """Describe a specific TPU VM."""
    return await tpu_request("GET", f"projects/{GCP_PROJECT}/locations/{zone}/nodes/{name}")


@router.post("/create")
async def create_tpu(
    name: str,
    accelerator_type: str = "v4-32",
    zone: str = DEFAULT_ZONE,
    runtime_version: str = "tpu-ubuntu2204-base",
    spot: bool = True,
):
    """Create a new TPU VM."""
    body = {
        "acceleratorType": accelerator_type,
        "runtimeVersion": runtime_version,
        "networkConfig": {"enableExternalIps": True},
    }
    if spot:
        body["schedulingConfig"] = {"preemptible": True}

    data = await tpu_request(
        "POST",
        f"projects/{GCP_PROJECT}/locations/{zone}/nodes?nodeId={name}",
        body=body,
        timeout=600,
    )
    if "error" in data:
        return {"error": data, "success": False}
    return {"success": True, "message": f"TPU {name} creation started", "operation": data}


@router.delete("/{name}")
async def delete_tpu(name: str, zone: str = DEFAULT_ZONE):
    """Delete a TPU VM."""
    data = await tpu_request("DELETE", f"projects/{GCP_PROJECT}/locations/{zone}/nodes/{name}")
    if "error" in data:
        return {"error": data, "success": False}
    return {"success": True, "message": f"TPU {name} deletion started"}


@router.get("/{name}/health")
async def check_tpu_health(name: str, zone: str = DEFAULT_ZONE):
    """Get TPU health from API (no SSH needed)."""
    data = await tpu_request("GET", f"projects/{GCP_PROJECT}/locations/{zone}/nodes/{name}")
    if "error" in data:
        return {"error": data, "healthy": False}
    return {
        "healthy": data.get("state") == "READY",
        "state": data.get("state", "UNKNOWN"),
        "health": data.get("health", "UNKNOWN"),
        "acceleratorType": data.get("acceleratorType", "").split("/")[-1],
        "ips": [ep.get("ipAddress") for ep in data.get("networkEndpoints", [])],
    }


# --- Current LOLM project status endpoint ---
@router.get("/status/overview")
async def project_overview():
    """Get full project overview — all TPUs, training runs, key metrics."""
    data = await tpu_request("GET", f"projects/{GCP_PROJECT}/locations/{DEFAULT_ZONE}/nodes")
    tpus = []
    for node in data.get("nodes", []):
        name = node.get("name", "").split("/")[-1]
        tpus.append({
            "name": name,
            "state": node.get("state", "UNKNOWN"),
            "type": node.get("acceleratorType", "").split("/")[-1],
            "spot": node.get("schedulingConfig", {}).get("preemptible", False),
        })

    return {
        "project": GCP_PROJECT,
        "zone": DEFAULT_ZONE,
        "tpus": tpus,
        "architecture": "LOLM — Latent Order Language Model",
        "paper": "Hybrid Transformer-SSM with 5 subsystems: Surface Decoder, Latent SSM, Persistent Memory, Regime Layer, Manifestation Gate",
        "current_run": {
            "name": "lolm-7b",
            "params": "~4.5B (d=4096, 32 layers, d_ff=8192)",
            "dataset": "FineWeb-Edu (HuggingFace streaming → local parquet)",
            "hardware": "v4-32 (16 chips, 32GB HBM/chip)",
            "status": "XLA compilation / HBM optimization in progress",
        },
        "completed_runs": [
            {"name": "LOLM-304M", "ppl": 68.37, "dataset": "WikiText-103", "result": "52.2% better than Pythia-410M"},
            {"name": "LOLM-1.57B", "ppl": 33.2, "dataset": "FineWeb-Edu", "result": "15% better than matched baseline"},
            {"name": "lolm-7b-base (decoder baseline)", "step": "~15000", "loss": "~5.1", "status": "training"},
        ],
    }
