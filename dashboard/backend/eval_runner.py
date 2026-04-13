"""Evaluation runner — run benchmarks on LOLM checkpoints from the dashboard."""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from auth import require_auth
from training import ssh_command, get_tpu_ips, _get_active_tpu, AVAILABLE_DATASETS

router = APIRouter(prefix="/api/eval", tags=["eval"], dependencies=[Depends(require_auth)])

DATA_DIR = Path("/opt/lolm-dashboard/data")
EVAL_RESULTS_FILE = DATA_DIR / "eval_results.json"

# Eval scripts to push to TPU
EVAL_SCRIPTS = ["evaluate.py", "downstream_eval.py", "downstream_eval_tpu.py", "eval_enterprise.py"]


def _load_eval_results() -> list:
    try:
        return json.loads(EVAL_RESULTS_FILE.read_text())
    except Exception:
        return []


def _save_eval_result(result: dict):
    results = _load_eval_results()
    results.append(result)
    results = results[-100:]  # Keep last 100
    EVAL_RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str))


@router.get("/results")
async def get_eval_results():
    """Get all saved evaluation results."""
    return {"results": _load_eval_results()}


@router.get("/available-checkpoints")
async def list_available_checkpoints(
    tpu_name: str = "",
    zone: str = "us-central2-b",
):
    """List checkpoints available for evaluation (local + GCS)."""
    name = tpu_name or _get_active_tpu()
    ips = await get_tpu_ips(name, zone)

    checkpoints = []

    # Local checkpoints on TPU
    if ips:
        rc, out, _ = await ssh_command(ips[0],
            "find ~/Latent/runs -name 'ckpt_*.pt' -printf '%p %s %T@\\n' 2>/dev/null | sort -k3 -rn",
            timeout=15,
        )
        for line in out.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 3:
                path = parts[0]
                size = int(parts[1])
                import re
                step_match = re.search(r'ckpt_(\d+)', path)
                step = int(step_match.group(1)) if step_match else 0
                checkpoints.append({
                    "path": path,
                    "step": step,
                    "size_gb": round(size / 1e9, 2),
                    "source": "local",
                })

    # GCS checkpoints
    import subprocess
    try:
        result = subprocess.run(
            ["gcloud", "storage", "ls", "-l", "gs://lolm-tpu-runs/nfet-stable/ckpt_*.pt"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if "ckpt_" in line and ".pt" in line:
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        size = int(parts[0])
                        path = parts[2]
                        step_match = re.search(r'ckpt_(\d+)', path)
                        step = int(step_match.group(1)) if step_match else 0
                        checkpoints.append({
                            "path": path,
                            "step": step,
                            "size_gb": round(size / 1e9, 2),
                            "source": "gcs",
                        })
    except Exception:
        pass

    # Deduplicate by step, prefer GCS
    seen = {}
    for ckpt in checkpoints:
        key = ckpt["step"]
        if key not in seen or ckpt["source"] == "gcs":
            seen[key] = ckpt
    checkpoints = sorted(seen.values(), key=lambda x: -x["step"])

    return {"checkpoints": checkpoints[:20]}  # Latest 20


@router.post("/run")
async def run_evaluation(
    checkpoint: str = "",
    benchmarks: str = "wikitext-103",  # Comma-separated: wikitext-103,hellaswag,lambada
    tpu_name: str = "",
    zone: str = "us-central2-b",
    config: str = "configs/scale/1b_lolm_pod.yaml",
):
    """Run evaluation benchmarks on a checkpoint.

    Runs on CPU on the TPU VM (doesn't interfere with training on TPU chips).
    Results are stored and returned.
    """
    name = tpu_name or _get_active_tpu()
    ips = await get_tpu_ips(name, zone)
    if not ips:
        return {"error": "No TPU IPs available"}

    # If no checkpoint specified, find the latest
    if not checkpoint:
        rc, out, _ = await ssh_command(ips[0],
            "ls -t ~/Latent/runs/*/ckpt_*.pt 2>/dev/null | head -1",
            timeout=10,
        )
        checkpoint = out.strip()
        if not checkpoint:
            return {"error": "No checkpoints found"}

    # If GCS checkpoint, download first
    if checkpoint.startswith("gs://"):
        local_path = f"/tmp/eval_{checkpoint.split('/')[-1]}"
        await ssh_command(ips[0],
            f"gcloud storage cp {checkpoint} {local_path}",
            timeout=600,
        )
        checkpoint = local_path

    # Build eval command
    benchmark_list = [b.strip() for b in benchmarks.split(",")]
    eval_id = f"eval_{int(time.time())}"

    # Run eval script on CPU (separate from TPU training)
    eval_cmd = (
        f"cd ~/Latent && python3 downstream_eval_tpu.py "
        f"--checkpoint {checkpoint} "
        f"--config {config} "
        f"--benchmarks {','.join(benchmark_list)} "
        f"--output /tmp/{eval_id}.json "
        f"2>&1"
    )

    # Run asynchronously
    rc, out, err = await ssh_command(ips[0], eval_cmd, timeout=1800)  # 30 min timeout

    # Parse results
    result = {
        "id": eval_id,
        "checkpoint": checkpoint,
        "benchmarks": benchmark_list,
        "config": config,
        "tpu": name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed" if rc == 0 else "failed",
        "raw_output": out[:2000],
    }

    # Try to read structured results
    rc2, json_out, _ = await ssh_command(ips[0],
        f"cat /tmp/{eval_id}.json 2>/dev/null", timeout=10)
    if rc2 == 0 and json_out.strip():
        try:
            result["results"] = json.loads(json_out)
        except Exception:
            pass

    _save_eval_result(result)
    return result


@router.post("/enterprise-report")
async def run_enterprise_report():
    """Run the enterprise value report on existing training logs."""
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "eval_enterprise.py", "--mode", "full-report",
             "--lolm-log", "tpu_results/full_lolm_live/log.jsonl",
             "--baseline-log", "tpu_results/matched_baseline_live/log.jsonl"],
            capture_output=True, text=True, timeout=60,
            cwd="/opt/lolm-dashboard/lolm",
        )
        return {"report": result.stdout, "error": result.stderr[:500] if result.stderr else None}
    except Exception as e:
        return {"error": str(e)}
