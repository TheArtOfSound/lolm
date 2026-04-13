"""Checkpoint management — list local TPU checkpoints + GCS, resume, download."""

import asyncio
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from auth import require_auth
from training import ssh_command, get_tpu_ips
from tpu import DEFAULT_ZONE

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"], dependencies=[Depends(require_auth)])


@router.get("")
@router.get("/")
async def list_checkpoints(tpu_name: str = "lolm-7b", zone: str = DEFAULT_ZONE):
    """List all local checkpoints on the TPU VM."""
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"checkpoints": [], "error": "No TPU IPs"}

    rc, out, _ = await ssh_command(ips[0],
        "find ~/Latent/runs -name 'ckpt_*.pt' -printf '%p %s %T@\\n' 2>/dev/null | sort -k3 -n",
        timeout=15,
    )
    checkpoints = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 3:
            path = parts[0]
            size_bytes = int(parts[1])
            timestamp = float(parts[2])
            name = os.path.basename(path)
            # Extract step from ckpt_NNNN.pt
            step_match = re.search(r'ckpt_(\d+)', name)
            step = int(step_match.group(1)) if step_match else 0
            # Extract run name from path
            run_dir = os.path.basename(os.path.dirname(path))
            checkpoints.append({
                "name": name,
                "path": path,
                "run": run_dir,
                "step": step,
                "size_gb": round(size_bytes / (1024**3), 2),
                "timestamp": timestamp,
                "tpu": tpu_name,
            })

    return {"checkpoints": sorted(checkpoints, key=lambda x: x["step"], reverse=True)}


@router.post("/resume")
async def resume_from_checkpoint(
    checkpoint_path: str,
    tpu_name: str = "lolm-7b",
    config: str = "configs/scale/1b_lolm_pod.yaml",
    zone: str = DEFAULT_ZONE,
):
    """Resume training from a specific checkpoint."""
    # Import here to avoid circular
    from training import _do_launch, get_tpu_ips, active_job, _save_active_job
    import time as _time

    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"success": False, "error": "No TPU IPs"}

    # Determine config from checkpoint path
    run_dir = os.path.basename(os.path.dirname(checkpoint_path))
    if "1b" in run_dir:
        config = "configs/scale/1b_lolm_pod.yaml"
    elif "2b" in run_dir:
        config = "configs/scale/2b_lolm_pod.yaml"
    elif "3b" in run_dir:
        config = "configs/scale/3b_lolm_pod.yaml"
    elif "7b" in run_dir:
        config = "configs/scale/7b_lolm_pod.yaml"

    result = await _do_launch(tpu_name, config, zone, ips, checkpoint_path, None, 0)

    if result["success"]:
        step_match = re.search(r'ckpt_(\d+)', checkpoint_path)
        step = int(step_match.group(1)) if step_match else 0
        return {"success": True, "message": f"Resumed from step {step} using {config}"}
    return {"success": False, "error": result.get("error", "Launch failed")}


@router.delete("/{name}")
async def delete_checkpoint(
    name: str,
    run: str = "",
    tpu_name: str = "lolm-7b",
    zone: str = DEFAULT_ZONE,
):
    """Delete a checkpoint from the TPU VM."""
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"success": False, "error": "No TPU IPs"}

    path = f"~/Latent/runs/{run}/{name}" if run else f"~/Latent/runs/*/{name}"
    rc, out, err = await ssh_command(ips[0], f"rm -f {path} && echo deleted", timeout=15)
    return {"success": "deleted" in out, "message": out.strip()}


@router.get("/download/{name}")
async def download_checkpoint(
    name: str,
    run: str = "",
    tpu_name: str = "lolm-7b",
    zone: str = DEFAULT_ZONE,
):
    """Download a checkpoint from TPU VM via SSH cat (streams the file)."""
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"error": "No TPU IPs"}

    path = f"~/Latent/runs/{run}/{name}" if run else f"$(find ~/Latent/runs -name '{name}' | head -1)"

    async def stream():
        cmd = ["ssh"] + f"-o StrictHostKeyChecking=no -o ConnectTimeout=15 -i /root/.ssh/google_compute_engine".split() + [
            f"bry@{ips[0]}", f"cat {path}"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            yield chunk
        await proc.wait()

    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={name}"},
    )
