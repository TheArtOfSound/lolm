"""Training job management with auto-retry failsafe and persistent logging."""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from auth import require_auth
from tpu import tpu_request, GCP_PROJECT, DEFAULT_ZONE

router = APIRouter(prefix="/api/training", tags=["training"], dependencies=[Depends(require_auth)])

SSH_KEY = "/root/.ssh/google_compute_engine"
SSH_USER = "bry"
SSH_OPTS = f"-o StrictHostKeyChecking=no -o ConnectTimeout=15 -o ServerAliveInterval=30 -i {SSH_KEY}"

# Persistent run data stored as JSON on the server
DATA_DIR = Path("/opt/lolm-dashboard/data")
DATA_DIR.mkdir(exist_ok=True)
RUNS_FILE = DATA_DIR / "runs.json"
ACTIVE_JOB_FILE = DATA_DIR / "active_job.json"
ACTIVE_JOBS_FILE = DATA_DIR / "active_jobs.json"

# Auto-retry config: reduce params on each retry
RETRY_CONFIGS = [
    # Attempt 1: original config as-is
    {},
    # Attempt 2: reduce d_ff
    {"model.d_ff": 8192},
    # Attempt 3: reduce d_ff + n_layers
    {"model.d_ff": 8192, "model.n_layers": 24},
]
MAX_RETRIES = 3


def _load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default if default is not None else {}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def _load_active_job() -> dict:
    return _load_json(ACTIVE_JOB_FILE, {})


def _save_active_job(job: dict):
    _save_json(ACTIVE_JOB_FILE, job)


def _load_runs() -> list:
    return _load_json(RUNS_FILE, [])


def _save_run(run: dict):
    runs = _load_runs()
    # Update existing or append
    for i, r in enumerate(runs):
        if r.get("id") == run.get("id"):
            runs[i] = run
            _save_json(RUNS_FILE, runs)
            return
    runs.append(run)
    _save_json(RUNS_FILE, runs)


# In-memory active job (also persisted to disk)
active_job: dict = _load_active_job()

# ── Multi-job support for comparison training ──────────────────────────────
from collections import deque

def _load_active_jobs() -> dict:
    return _load_json(ACTIVE_JOBS_FILE, {})

def _save_active_jobs(jobs: dict):
    _save_json(ACTIVE_JOBS_FILE, jobs)

active_jobs: dict[str, dict] = _load_active_jobs()
metrics_history: dict[str, deque] = {}
raw_log_lines: dict[str, deque] = {}
_tailer_tasks: dict[str, asyncio.Task] = {}


async def _tail_job_logs(label: str, ip: str):
    """Background: SSH tail -f on a job's log, feeding metrics_history."""
    if label not in metrics_history:
        metrics_history[label] = deque(maxlen=5000)
    if label not in raw_log_lines:
        raw_log_lines[label] = deque(maxlen=200)

    # Backfill existing log
    rc, out, _ = await ssh_command(ip, "cat ~/train_pod.log 2>/dev/null", timeout=30)
    if rc == 0 and out.strip():
        for line in out.strip().split("\n"):
            parsed = parse_log_line(line)
            if parsed:
                metrics_history[label].append(parsed)
            raw_log_lines[label].append(line)

    # Live tail
    cmd = ["ssh"] + SSH_OPTS.split() + [f"{SSH_USER}@{ip}", "tail -f ~/train_pod.log"]
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=300)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                raw_log_lines[label].append(text)
                parsed = parse_log_line(text)
                if parsed:
                    metrics_history[label].append(parsed)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass
        await asyncio.sleep(10)


def _start_tailer(label: str, ip: str):
    if label in _tailer_tasks and not _tailer_tasks[label].done():
        return
    _tailer_tasks[label] = asyncio.create_task(_tail_job_logs(label, ip))


def _stop_tailer(label: str):
    if label in _tailer_tasks:
        _tailer_tasks[label].cancel()
        del _tailer_tasks[label]


# ── Preemption Watchdog — auto-recover from spot TPU preemption ────────────

_watchdog_task = None

AVAILABLE_DATASETS = {
    "fineweb-edu": "HuggingFaceFW/fineweb-edu",
    "fineweb": "HuggingFaceFW/fineweb",
    "the-pile": "EleutherAI/the_pile_deduplicated",
    "redpajama": "togethercomputer/RedPajama-Data-1T-Sample",
    "tinystories": "roneneldan/TinyStories",
    "custom": None,  # User provides path
}

# TPU setup script — installs deps, clones repo
TPU_SETUP_SCRIPT = """
ls ~/Latent/train_tpu_pod.py 2>/dev/null && echo 'repo exists' || git clone https://github.com/TheArtOfSound/lolm.git ~/Latent
pip install tiktoken datasets huggingface_hub pyarrow pyyaml torch~=2.4.0 'torch_xla[tpu]~=2.4.0' -f https://storage.googleapis.com/libtpu-releases/index.html -f https://storage.googleapis.com/libtpu-wheels/index.html 2>&1 | tail -1
echo SETUP_DONE
"""


async def _get_tpu_state(tpu_name: str, zone: str = DEFAULT_ZONE) -> str:
    """Get TPU state via REST API. Returns 'READY', 'PREEMPTED', 'NOT_FOUND', etc."""
    data = await tpu_request("GET", f"projects/{GCP_PROJECT}/locations/{zone}/nodes/{tpu_name}")
    if "error" in data:
        error_msg = str(data.get("error", ""))
        if "NOT_FOUND" in error_msg or "was not found" in error_msg:
            return "NOT_FOUND"
        return "ERROR"
    return data.get("state", "UNKNOWN")


async def _find_latest_gcs_checkpoint(gcs_path: str) -> str:
    """Find latest checkpoint in GCS by reading latest.txt."""
    rc, out, _ = await asyncio.create_subprocess_exec(
        "gcloud", "storage", "cat", f"{gcs_path.rstrip('/')}/latest.txt",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    ).communicate() if False else (None, None, None)
    # Use ssh_command approach instead — run from server
    import subprocess
    try:
        result = subprocess.run(
            ["gcloud", "storage", "cat", f"{gcs_path.rstrip('/')}/latest.txt"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            ckpt_name = result.stdout.strip()
            return f"{gcs_path.rstrip('/')}/{ckpt_name}"
    except Exception:
        pass
    return ""


async def _auto_recover(label: str, job: dict):
    """Auto-recover from preemption: create new TPU, resume from GCS."""
    global active_jobs
    import subprocess

    tpu_name = job.get("tpu_name", "lolm-train")
    zone = job.get("zone", DEFAULT_ZONE)
    config = job.get("config", "configs/scale/1b_lolm_pod.yaml")
    gcs_path = job.get("gcs_path", "gs://lolm-tpu-runs/nfet-stable/")
    accel_type = job.get("accelerator_type", "v4-8")

    print(f"[WATCHDOG] Preemption detected for {label} ({tpu_name}). Auto-recovering...", flush=True)

    # Update status
    active_jobs[label]["status"] = "recovering"
    active_jobs[label]["recovery_count"] = active_jobs[label].get("recovery_count", 0) + 1
    _save_active_jobs(active_jobs)

    # 1. Delete preempted TPU
    try:
        await tpu_request("DELETE", f"projects/{GCP_PROJECT}/locations/{zone}/nodes/{tpu_name}")
        await asyncio.sleep(30)  # Wait for delete
    except Exception:
        pass

    # 2. Create new spot TPU
    body = {
        "acceleratorType": accel_type,
        "runtimeVersion": "tpu-ubuntu2204-base",
        "networkConfig": {"enableExternalIps": True},
        "schedulingConfig": {"preemptible": True},
    }

    print(f"[WATCHDOG] Creating new {accel_type} in {zone}...", flush=True)
    create_result = await tpu_request(
        "POST",
        f"projects/{GCP_PROJECT}/locations/{zone}/nodes?nodeId={tpu_name}",
        body=body, timeout=600,
    )
    if "error" in create_result:
        print(f"[WATCHDOG] Create failed: {create_result}", flush=True)
        active_jobs[label]["status"] = "recovery_failed"
        _save_active_jobs(active_jobs)
        return

    # Wait for READY state
    for _ in range(60):
        state = await _get_tpu_state(tpu_name, zone)
        if state == "READY":
            break
        await asyncio.sleep(10)
    else:
        print(f"[WATCHDOG] TPU never reached READY state", flush=True)
        active_jobs[label]["status"] = "recovery_failed"
        _save_active_jobs(active_jobs)
        return

    # 3. Get IPs and setup
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        active_jobs[label]["status"] = "recovery_failed"
        _save_active_jobs(active_jobs)
        return

    # 4. Setup all workers
    for ip in ips:
        await ssh_command(ip, TPU_SETUP_SCRIPT, timeout=600)

    # 5. Find latest GCS checkpoint
    resume_path = await _find_latest_gcs_checkpoint(gcs_path)
    print(f"[WATCHDOG] Resuming from: {resume_path or 'scratch'}", flush=True)

    # 6. Launch training
    dataset = job.get("dataset")
    result = await _do_launch(
        tpu_name, config, zone, ips, resume_path or None, gcs_path, 0,
        dataset=dataset,
    )

    if result.get("success"):
        active_jobs[label]["status"] = "running"
        active_jobs[label]["ips"] = ips
        active_jobs[label]["recovered_at"] = datetime.now(timezone.utc).isoformat()
        _save_active_jobs(active_jobs)
        # Restart tailer
        _start_tailer(label, ips[0])
        print(f"[WATCHDOG] Recovery successful! Training resumed.", flush=True)
    else:
        active_jobs[label]["status"] = "recovery_failed"
        _save_active_jobs(active_jobs)
        print(f"[WATCHDOG] Recovery failed: {result}", flush=True)


async def _preemption_watchdog():
    """Background task: check all active jobs every 60s for preemption."""
    while True:
        try:
            for label, job in list(active_jobs.items()):
                if job.get("status") not in ("running", "recovering"):
                    continue
                if job.get("status") == "recovering":
                    continue  # Already recovering

                tpu_name = job.get("tpu_name")
                zone = job.get("zone", DEFAULT_ZONE)
                if not tpu_name:
                    continue

                state = await _get_tpu_state(tpu_name, zone)
                if state in ("PREEMPTED", "NOT_FOUND"):
                    max_recoveries = 10
                    if job.get("recovery_count", 0) < max_recoveries:
                        await _auto_recover(label, job)
                    else:
                        print(f"[WATCHDOG] Max recoveries reached for {label}", flush=True)
                        active_jobs[label]["status"] = "max_recoveries"
                        _save_active_jobs(active_jobs)
        except Exception as e:
            print(f"[WATCHDOG] Error: {e}", flush=True)

        await asyncio.sleep(60)


def start_watchdog():
    """Start the preemption watchdog background task."""
    global _watchdog_task
    if _watchdog_task and not _watchdog_task.done():
        return
    _watchdog_task = asyncio.create_task(_preemption_watchdog())
    print("[WATCHDOG] Preemption watchdog started", flush=True)


async def get_tpu_ips(tpu_name: str, zone: str = DEFAULT_ZONE) -> list[str]:
    """Get external IPs of all workers in a TPU VM via REST API."""
    data = await tpu_request("GET", f"projects/{GCP_PROJECT}/locations/{zone}/nodes/{tpu_name}")
    ips = []
    for ep in data.get("networkEndpoints", []):
        ac = ep.get("accessConfig", {})
        ip = ac.get("externalIp", "")
        if ip:
            ips.append(ip)
    return ips


async def ssh_command(ip: str, command: str, timeout: int = 60) -> tuple[int, str, str]:
    """SSH to a TPU VM worker by IP."""
    cmd = ["ssh"] + SSH_OPTS.split() + [f"{SSH_USER}@{ip}", command]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "SSH timed out"
    return proc.returncode, stdout.decode(), stderr.decode()


async def _do_launch(tpu_name: str, config: str, zone: str, ips: list[str],
                     resume: Optional[str], gcs_path: Optional[str],
                     xla_opt_level: int, config_overrides: dict = {},
                     dataset: Optional[str] = None) -> dict:
    """Internal launch — SSHs to all workers and starts training in tmux."""

    # Build training command
    parts = [
        "cd ~/Latent",
        "export PJRT_DEVICE=TPU",
        f"export XLA_FLAGS='--xla_backend_optimization_level={xla_opt_level}'",
        f"python3 train_tpu_pod.py --config {config}",
    ]
    # If a custom dataset is specified, override via environment variable
    if dataset:
        parts.insert(2, f"export LOLM_DATASET='{dataset}'")
    if resume:
        parts[-1] += f" --resume {resume}"
    if gcs_path:
        parts[-1] += f" --gcs {gcs_path}"
    train_cmd = " && ".join(parts) + " 2>&1 | tee ~/train_pod.log"

    # Kill existing + pull code
    for ip in ips:
        await ssh_command(ip,
            "tmux kill-session -t train 2>/dev/null; "
            "pkill -9 python3 2>/dev/null; "
            "cd ~/Latent && git fetch origin main && git reset --hard origin/main 2>/dev/null; "
            "find ~/Latent -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; "
            "echo ready",
            timeout=120,
        )

    await asyncio.sleep(3)

    # Clean accel devices
    for ip in ips:
        await ssh_command(ip,
            "PIDS=$(fuser /dev/accel0 /dev/accel1 /dev/accel2 /dev/accel3 2>/dev/null | grep -oP '\\d+' | sort -u | tr '\\n' ' '); "
            "[ -n \"$PIDS\" ] && kill -9 $PIDS 2>/dev/null; sleep 2; echo cleaned",
            timeout=30,
        )

    await asyncio.sleep(2)

    # Launch in tmux — non-master first
    worker_order = list(range(1, len(ips))) + [0]
    for idx in worker_order:
        ip = ips[idx]
        rc, out, err = await ssh_command(ip,
            f"tmux new-session -d -s train '{train_cmd}'",
            timeout=30,
        )
        if rc != 0:
            return {"success": False, "error": f"Worker {idx} ({ip}) failed: {err}"}
        await asyncio.sleep(2)

    return {"success": True}


async def _check_if_crashed(ips: list[str]) -> tuple[bool, str]:
    """Check if training crashed by looking at tmux + last log line."""
    if not ips:
        return True, "No IPs"
    rc, out, _ = await ssh_command(ips[0],
        "tmux has-session -t train 2>/dev/null && echo RUNNING || echo STOPPED; "
        "tail -3 ~/train_pod.log 2>/dev/null",
        timeout=15,
    )
    lines = out.strip().split("\n") if out.strip() else []
    running = len(lines) > 0 and lines[0] == "RUNNING"
    last_lines = " ".join(lines[1:])
    if not running and ("RESOURCE_EXHAUSTED" in last_lines or "Error" in last_lines):
        return True, last_lines[-200:]
    return not running, last_lines[-200:] if not running else ""


@router.post("/launch")
async def launch_training(
    tpu_name: str = "lolm-7b",
    config: str = "configs/scale/1b_lolm_pod.yaml",
    zone: str = DEFAULT_ZONE,
    resume: Optional[str] = None,
    gcs_path: Optional[str] = None,
    xla_opt_level: int = 0,
    auto_retry: bool = True,
    dataset: Optional[str] = None,
):
    """Launch LOLM training with auto-retry failsafe.

    If auto_retry=True and training crashes with OOM, automatically retries
    up to 3 times with progressively reduced parameters:
      Attempt 1: Original config
      Attempt 2: d_ff reduced to 8192
      Attempt 3: d_ff=8192 + n_layers=24
    """
    global active_job

    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"success": False, "error": f"Could not get IPs for {tpu_name}"}

    # Create run record
    run_id = f"run_{int(time.time())}"
    run = {
        "id": run_id,
        "tpu_name": tpu_name,
        "zone": zone,
        "config": config,
        "resume": resume,
        "gcs_path": gcs_path,
        "auto_retry": auto_retry,
        "attempts": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "launching",
    }

    # Launch with retry loop
    for attempt in range(MAX_RETRIES if auto_retry else 1):
        overrides = RETRY_CONFIGS[attempt] if attempt < len(RETRY_CONFIGS) else RETRY_CONFIGS[-1]

        attempt_record = {
            "attempt": attempt + 1,
            "overrides": overrides,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "launching",
        }

        result = await _do_launch(tpu_name, config, zone, ips, resume, gcs_path, xla_opt_level, overrides, dataset=dataset)

        if not result["success"]:
            attempt_record["status"] = "launch_failed"
            attempt_record["error"] = result.get("error", "")
            run["attempts"].append(attempt_record)
            continue

        attempt_record["status"] = "running"
        run["attempts"].append(attempt_record)
        run["status"] = "running"
        run["current_attempt"] = attempt + 1

        active_job = {
            "tpu_name": tpu_name,
            "zone": zone,
            "config": config,
            "ips": ips,
            "run_id": run_id,
            "attempt": attempt + 1,
            "overrides": overrides,
            "auto_retry": auto_retry,
            "gcs_path": gcs_path or "gs://lolm-tpu-runs/nfet-stable/",
            "dataset": dataset,
            "accelerator_type": "v4-8",  # Default, updated by TPU describe
            "recovery_count": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "model_type": "lolm",
        }
        _save_active_job(active_job)
        _save_run(run)

        # Also update multi-job tracking for watchdog
        active_jobs["lolm"] = dict(active_job)
        _save_active_jobs(active_jobs)

        # Start tailer + watchdog
        _start_tailer("lolm", ips[0])

        return {
            "success": True,
            "message": f"Training launched on {tpu_name} ({len(ips)} workers), attempt {attempt + 1}/{MAX_RETRIES}",
            "job": active_job,
            "run_id": run_id,
        }

    run["status"] = "failed"
    _save_run(run)
    return {"success": False, "error": "All launch attempts failed", "run": run}


@router.post("/stop")
async def stop_training(tpu_name: Optional[str] = None, zone: str = DEFAULT_ZONE):
    """Stop training on all workers."""
    global active_job
    name = tpu_name or active_job.get("tpu_name")
    if not name:
        return {"error": "No active job"}

    ips = active_job.get("ips") or await get_tpu_ips(name, zone)
    for ip in ips:
        await ssh_command(ip,
            "tmux kill-session -t train 2>/dev/null; pkill -9 python3 2>/dev/null",
            timeout=15,
        )

    active_job["status"] = "stopped"
    _save_active_job(active_job)

    # Update run record
    if active_job.get("run_id"):
        runs = _load_runs()
        for r in runs:
            if r["id"] == active_job["run_id"]:
                r["status"] = "stopped"
                r["ended_at"] = datetime.now(timezone.utc).isoformat()
        _save_json(RUNS_FILE, runs)

    return {"success": True}


@router.get("/status")
async def get_training_status(tpu_name: Optional[str] = None, zone: str = DEFAULT_ZONE):
    """Check if training is running + get recent log."""
    global active_job
    name = tpu_name or active_job.get("tpu_name", "lolm-7b")
    ips = active_job.get("ips") or await get_tpu_ips(name, zone)
    if not ips:
        return {"running": False, "job": active_job, "log_tail": []}

    rc, out, _ = await ssh_command(ips[0],
        "tmux has-session -t train 2>/dev/null && echo RUNNING || echo STOPPED; "
        "tail -10 ~/train_pod.log 2>/dev/null",
        timeout=15,
    )
    lines = out.strip().split("\n") if out.strip() else []
    running = len(lines) > 0 and lines[0] == "RUNNING"
    log_tail = lines[1:] if len(lines) > 1 else []

    # Detect crash and trigger auto-retry
    if not running and active_job.get("status") == "running" and active_job.get("auto_retry"):
        last_log = " ".join(log_tail)
        if "RESOURCE_EXHAUSTED" in last_log:
            attempt = active_job.get("attempt", 1)
            if attempt < MAX_RETRIES:
                # Auto-retry with reduced params
                active_job["status"] = f"retrying (attempt {attempt + 1}/{MAX_RETRIES})"
                _save_active_job(active_job)
                # Schedule retry in background
                asyncio.create_task(_auto_retry(active_job))

    return {"running": running, "log_tail": log_tail, "job": active_job}


async def _auto_retry(job: dict):
    """Background task: retry training with reduced params after OOM."""
    global active_job
    attempt = job.get("attempt", 1)
    if attempt >= MAX_RETRIES:
        active_job["status"] = "failed (max retries)"
        _save_active_job(active_job)
        return

    next_attempt = attempt + 1
    overrides = RETRY_CONFIGS[next_attempt - 1] if next_attempt - 1 < len(RETRY_CONFIGS) else RETRY_CONFIGS[-1]

    # Wait a bit for cleanup
    await asyncio.sleep(10)

    ips = job.get("ips", [])
    if not ips:
        ips = await get_tpu_ips(job["tpu_name"], job.get("zone", DEFAULT_ZONE))

    result = await _do_launch(
        job["tpu_name"], job["config"], job.get("zone", DEFAULT_ZONE),
        ips, job.get("resume"), job.get("gcs_path"), 0, overrides,
    )

    if result["success"]:
        active_job["attempt"] = next_attempt
        active_job["overrides"] = overrides
        active_job["status"] = "running"
        active_job["retry_reason"] = f"OOM on attempt {attempt}, reduced params: {overrides}"
        _save_active_job(active_job)

        # Update run record
        if job.get("run_id"):
            runs = _load_runs()
            for r in runs:
                if r["id"] == job["run_id"]:
                    r["attempts"].append({
                        "attempt": next_attempt,
                        "overrides": overrides,
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "status": "running",
                    })
                    r["current_attempt"] = next_attempt
            _save_json(RUNS_FILE, runs)
    else:
        active_job["status"] = f"retry {next_attempt} failed"
        _save_active_job(active_job)


@router.get("/model-info")
async def get_model_info(tpu_name: Optional[str] = None, zone: str = DEFAULT_ZONE):
    """Get model info from the beginning of the training log (params, chips, dataset, config)."""
    name = tpu_name or active_job.get("tpu_name", "lolm-7b")
    ips = active_job.get("ips") or await get_tpu_ips(name, zone)
    if not ips:
        return {}

    rc, out, _ = await ssh_command(ips[0], "head -60 ~/train_pod.log 2>/dev/null", timeout=15)
    info = {}
    for line in out.strip().split("\n"):
        if "total:" in line:
            import re as _re
            m = _re.search(r'([\d,]+)', line)
            if m:
                info["params"] = f"{int(m.group(1).replace(',', '')) / 1e9:.2f}B"
        if "Global batch:" in line:
            m = _re.search(r'Global batch:\s*(\d+)', line)
            if m:
                info["batch"] = int(m.group(1))
        if "Chips:" in line:
            m = _re.search(r'Chips:\s*(\d+)', line)
            if m:
                info["chips"] = int(m.group(1))
        if "Config:" in line:
            info["config"] = line.split("Config:")[-1].strip()
        if "fineweb" in line.lower():
            info["dataset"] = "FineWeb-Edu"
        elif "tinystories" in line.lower():
            info["dataset"] = "TinyStories"
        elif "hf_parquet_local" in line.lower():
            info["dataset"] = "FineWeb-Edu"  # Pre-downloaded HF parquets
        elif "parquet" in line.lower() and "dataset" not in info:
            info["dataset"] = "Local Parquet"
        if "FSDP wrapping complete" in line:
            info["fsdp"] = True
        if "single-device" in line:
            info["fsdp"] = False
    return info


@router.get("/log/recent")
async def get_recent_log(tpu_name: Optional[str] = None, zone: str = DEFAULT_ZONE, lines: int = 100):
    """Get recent log lines."""
    name = tpu_name or active_job.get("tpu_name", "lolm-7b")
    ips = active_job.get("ips") or await get_tpu_ips(name, zone)
    if not ips:
        return {"lines": []}

    rc, out, _ = await ssh_command(ips[0], f"tail -{lines} ~/train_pod.log 2>/dev/null", timeout=15)
    return {"lines": out.strip().split("\n") if out.strip() else []}


@router.get("/runs")
async def list_runs():
    """List all saved training runs."""
    return {"runs": _load_runs()}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get a specific run."""
    for r in _load_runs():
        if r["id"] == run_id:
            return r
    return {"error": "Not found"}


def parse_log_line(line: str) -> Optional[dict]:
    """Parse a training step log line into structured metrics.

    Handles the format from train_tpu_pod.py:
    step   10 | loss 148.9 | tok 146.5 | ppl 485165195.4 | fut 6.09 | lr 1.35e-06 | 0.4 steps/s | 0.00B tok | gate=0.379 | regimes=32 | chg=0.006 | comp=0.086 | reg=-2.153 | mem=1.000 | man=0.378
    """
    if not line.strip().startswith("step"):
        return None
    metrics = {}
    step_match = re.search(r'step\s+(\d+)', line)
    if step_match:
        metrics["step"] = int(step_match.group(1))

    # Primary metrics (space-separated key value)
    for key, pattern in {
        "loss": r'\|\s*loss\s+([-\d.]+)',
        "loss_tok": r'\|\s*tok\s+([-\d.]+)',
        "ppl": r'\|\s*ppl\s+([-\d.]+)',
        "loss_future": r'\|\s*fut\s+([-\d.]+)',
        "lr": r'\|\s*lr\s+([-\d.e+]+)',
        "steps_per_sec": r'([\d.]+)\s+steps/s',
    }.items():
        m = re.search(pattern, line)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except ValueError:
                pass

    # Key=value metrics
    for key, pattern in {
        "gate": r'gate=([-\d.]+)',
        "regimes": r'regimes=(\d+)',
        "loss_changepoint": r'chg=([-\d.]+)',
        "loss_competitive": r'comp=([-\d.]+)',
        "loss_regime": r'reg=([-\d.]+)',
        "loss_mem": r'mem=([-\d.]+)',
        "loss_manifest": r'man=([-\d.]+)',
    }.items():
        m = re.search(pattern, line)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except ValueError:
                pass

    return metrics if "step" in metrics else None


# ── Comparison endpoints ──────────────────────────────────────────────────

@router.get("/compare")
async def compare_training():
    """Return metrics from all active jobs for side-by-side comparison."""
    result = {}
    for label, job in active_jobs.items():
        history = list(metrics_history.get(label, []))
        # Downsample to max 500 points
        n = len(history)
        step = max(1, n // 500)
        downsampled = history[::step]

        result[label] = {
            "label": label,
            "tpu_name": job.get("tpu_name", ""),
            "config": job.get("config", ""),
            "status": job.get("status", "unknown"),
            "model_type": job.get("model_type", label),
            "latest": history[-1] if history else {},
            "history": downsampled,
        }
    return {"jobs": result, "timestamp": time.time()}


@router.get("/jobs")
async def list_active_jobs():
    """List all active training jobs."""
    return {"jobs": active_jobs}


@router.post("/launch-pair")
async def launch_pair(
    lolm_tpu: str = "lolm-run-1",
    lolm_config: str = "configs/scale/1b_lolm_pod.yaml",
    baseline_tpu: str = "lolm-run-2",
    baseline_config: str = "configs/scale/870m_baseline_v4-8.yaml",
    zone: str = DEFAULT_ZONE,
    dataset: Optional[str] = None,
):
    """Launch LOLM + baseline training simultaneously on separate TPUs."""
    global active_jobs

    results = {}
    for label, tpu, config, mtype in [
        ("lolm", lolm_tpu, lolm_config, "lolm"),
        ("baseline", baseline_tpu, baseline_config, "baseline"),
    ]:
        ips = await get_tpu_ips(tpu, zone)
        if not ips:
            results[label] = {"success": False, "error": f"No IPs for {tpu}"}
            continue

        result = await _do_launch(tpu, config, zone, ips, None, None, 0, {}, dataset=dataset)
        job = {
            "tpu_name": tpu,
            "zone": zone,
            "config": config,
            "ips": ips,
            "run_id": f"run_{int(time.time())}_{label}",
            "attempt": 1,
            "overrides": {},
            "auto_retry": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running" if result["success"] else "failed",
            "model_type": mtype,
        }
        active_jobs[label] = job
        results[label] = {"success": result["success"], "job": job}

        if result["success"] and ips:
            _start_tailer(label, ips[0])

    _save_active_jobs(active_jobs)
    return {"results": results}


@router.get("/compare-logs")
async def compare_logs(label: str = "lolm", lines: int = 50):
    """Get recent raw log lines for a specific job."""
    log = list(raw_log_lines.get(label, []))
    return {"lines": log[-lines:]}


@router.get("/datasets")
async def list_datasets():
    """List available training datasets."""
    return {"datasets": [
        {"id": "fineweb-edu", "name": "FineWeb-Edu", "tokens": "~15B", "description": "Curated educational web text"},
        {"id": "fineweb", "name": "FineWeb", "tokens": "~627B", "description": "Large web crawl"},
        {"id": "the-pile", "name": "The Pile", "tokens": "~300B", "description": "Diverse text corpus (EleutherAI)"},
        {"id": "redpajama", "name": "RedPajama Sample", "tokens": "~1B", "description": "Open-source LLaMA data replica"},
        {"id": "tinystories", "name": "TinyStories", "tokens": "~0.5B", "description": "Short children's stories for small models"},
    ]}


@router.get("/watchdog-status")
async def watchdog_status():
    """Get auto-recovery watchdog status."""
    return {
        "active": _watchdog_task is not None and not _watchdog_task.done(),
        "jobs": {
            label: {
                "status": job.get("status"),
                "recovery_count": job.get("recovery_count", 0),
                "tpu_name": job.get("tpu_name"),
                "gcs_path": job.get("gcs_path"),
            }
            for label, job in active_jobs.items()
        },
    }


async def start_tailers_for_active_jobs():
    """Start background tailers for any jobs marked as running. Called on app startup."""
    for label, job in active_jobs.items():
        if job.get("status") == "running":
            ips = job.get("ips", [])
            if ips:
                _start_tailer(label, ips[0])
