"""Supabase CRUD for training runs and step metrics."""

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends
from auth import require_auth

router = APIRouter(prefix="/api/runs", tags=["runs"], dependencies=[Depends(require_auth)])

# Supabase client — lazy init
_supabase = None


def get_supabase():
    global _supabase
    if _supabase is None:
        try:
            from supabase import create_client
            url = os.environ.get("SUPABASE_URL", "")
            key = os.environ.get("SUPABASE_KEY", "")
            if url and key:
                _supabase = create_client(url, key)
        except Exception:
            pass
    return _supabase


@router.get("")
@router.get("/")
async def list_runs(limit: int = 50):
    """List all training runs."""
    sb = get_supabase()
    if not sb:
        return {"runs": [], "warning": "Supabase not configured"}
    try:
        result = sb.table("lolm_runs").select("*").order("created_at", desc=True).limit(limit).execute()
        return {"runs": result.data}
    except Exception as e:
        return {"runs": [], "error": str(e)}


@router.get("/{run_id}")
async def get_run(run_id: str):
    """Get a specific run."""
    sb = get_supabase()
    if not sb:
        return {"error": "Supabase not configured"}
    try:
        result = sb.table("lolm_runs").select("*").eq("id", run_id).single().execute()
        return result.data
    except Exception as e:
        return {"error": str(e)}


@router.get("/{run_id}/metrics")
async def get_run_metrics(run_id: str, limit: int = 5000):
    """Get step metrics for a run."""
    sb = get_supabase()
    if not sb:
        return {"metrics": [], "warning": "Supabase not configured"}
    try:
        result = (sb.table("lolm_step_metrics")
                  .select("*")
                  .eq("run_id", run_id)
                  .order("step")
                  .limit(limit)
                  .execute())
        return {"metrics": result.data}
    except Exception as e:
        return {"metrics": [], "error": str(e)}


def create_run(name: str, config_snapshot: dict, tpu_name: str, tpu_type: str,
               tpu_zone: str, max_steps: int, gcs_path: Optional[str] = None) -> Optional[str]:
    """Create a new training run record. Returns run_id or None."""
    sb = get_supabase()
    if not sb:
        return None
    run_id = str(uuid4())
    try:
        sb.table("lolm_runs").insert({
            "id": run_id,
            "name": name,
            "config_snapshot": config_snapshot,
            "tpu_name": tpu_name,
            "tpu_type": tpu_type,
            "tpu_zone": tpu_zone,
            "gcs_path": gcs_path,
            "status": "running",
            "current_step": 0,
            "max_steps": max_steps,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return run_id
    except Exception:
        return None


def insert_metrics(run_id: str, metrics: list[dict]):
    """Batch insert step metrics."""
    sb = get_supabase()
    if not sb or not metrics:
        return
    try:
        rows = [{"run_id": run_id, **m, "recorded_at": datetime.now(timezone.utc).isoformat()} for m in metrics]
        sb.table("lolm_step_metrics").insert(rows).execute()
    except Exception:
        pass


def update_run_status(run_id: str, status: str, current_step: Optional[int] = None,
                      error_message: Optional[str] = None):
    """Update run status."""
    sb = get_supabase()
    if not sb:
        return
    update = {"status": status}
    if current_step is not None:
        update["current_step"] = current_step
    if error_message:
        update["error_message"] = error_message
    if status in ("completed", "failed", "stopped"):
        update["ended_at"] = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("lolm_runs").update(update).eq("id", run_id).execute()
    except Exception:
        pass
