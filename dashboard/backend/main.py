"""LOLM Training Command Center — FastAPI backend.

Bridges the web UI to Google Cloud TPU infrastructure via gcloud CLI.
All data is real — no simulation, no mock data.
"""

import os
import re
import time
from pathlib import Path
from typing import Optional
from collections import deque

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from auth import require_auth
import tpu
import training
import logs
import config_manager
import checkpoints
import db
import benchmarks
import analysis
import chat


# ── Notification system ────────────────────────────────────────────────────

class Notification(BaseModel):
    id: int
    type: str  # "milestone", "error", "info", "warning"
    title: str
    message: str
    timestamp: float
    step: Optional[int] = None

# In-memory ring buffer (survives across requests, cleared on restart)
_notifications: deque = deque(maxlen=200)
_notification_counter = 0
_seen_milestones: set = set()

STEP_MILESTONES = {1, 10, 100, 500, 1000, 5000, 10000, 25000, 50000}


def _add_notification(ntype: str, title: str, message: str, step: Optional[int] = None):
    global _notification_counter
    _notification_counter += 1
    _notifications.append({
        "id": _notification_counter,
        "type": ntype,
        "title": title,
        "message": message,
        "timestamp": time.time(),
        "step": step,
    })


def parse_notifications_from_log(line: str):
    """Parse a log line and emit notifications for notable events."""
    global _seen_milestones

    # Detect step milestones
    step_match = re.search(r"step[=:\s]+(\d+)", line, re.IGNORECASE)
    if step_match:
        step_num = int(step_match.group(1))
        if step_num in STEP_MILESTONES and step_num not in _seen_milestones:
            _seen_milestones.add(step_num)
            loss_match = re.search(r"loss[=:\s]+([\d.]+)", line)
            loss_str = f", loss={loss_match.group(1)}" if loss_match else ""
            _add_notification(
                "milestone",
                f"Step {step_num:,} reached",
                f"Training reached step {step_num:,}{loss_str}",
                step=step_num,
            )

    # OOM detection
    if re.search(r"(out.of.memory|OOM|RESOURCE_EXHAUSTED|HBM)", line, re.IGNORECASE):
        _add_notification("error", "OOM Error", line.strip()[:200])

    # Preemption detection
    if re.search(r"(preempt|PREEMPTED|spot.instance.terminated)", line, re.IGNORECASE):
        _add_notification("warning", "TPU Preempted", line.strip()[:200])

    # NaN detection
    if re.search(r"(nan|NaN|loss.*inf)", line):
        _add_notification("error", "NaN Detected", line.strip()[:200])

    # XLA compilation complete
    if re.search(r"(compilation.*complete|XLA.*compiled|graph.*compiled)", line, re.IGNORECASE):
        _add_notification("info", "XLA Compilation Complete", "XLA graph compilation finished")

    # Training started
    if re.search(r"(training.*start|begin.*training|starting.*train)", line, re.IGNORECASE):
        _seen_milestones.clear()
        _add_notification("info", "Training Started", line.strip()[:200])

app = FastAPI(
    title="LOLM Training Command Center",
    description="Real-time TPU training management for the Latent Order Language Model",
    version="1.0.0",
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://lolm.autohustle.online"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(tpu.router)
app.include_router(training.router)
app.include_router(logs.router)
app.include_router(config_manager.router)
app.include_router(checkpoints.router)
app.include_router(db.router)
app.include_router(benchmarks.router)
app.include_router(analysis.router)
app.include_router(chat.router)

# Comparison page (self-contained HTML, no React needed)
import compare
app.include_router(compare.router)


@app.on_event("startup")
async def startup_event():
    """Start background log tailers for any active comparison jobs."""
    from training import start_tailers_for_active_jobs
    await start_tailers_for_active_jobs()


@app.get("/health")
async def health():
    """Health check — no auth required."""
    return {"status": "ok", "service": "lolm-command-center"}


@app.get("/api/auth/verify")
async def verify_auth(_=Depends(require_auth)):
    """Verify authentication."""
    return {"authenticated": True}


# ── Notification endpoints ─────────────────────────────────────────────────

@app.get("/api/notifications")
async def get_notifications(
    limit: int = Query(default=50, le=200),
    since_id: int = Query(default=0),
    _=Depends(require_auth),
):
    """Return recent notifications, optionally only those after since_id."""
    items = [n for n in _notifications if n["id"] > since_id]
    items = sorted(items, key=lambda n: n["timestamp"], reverse=True)[:limit]
    return {
        "notifications": items,
        "total": len(_notifications),
        "latest_id": _notifications[-1]["id"] if _notifications else 0,
    }


@app.get("/api/notifications/count")
async def get_notification_count(
    since_id: int = Query(default=0),
    _=Depends(require_auth),
):
    """Return count of new notifications since since_id."""
    count = sum(1 for n in _notifications if n["id"] > since_id)
    return {"count": count, "latest_id": _notifications[-1]["id"] if _notifications else 0}


@app.post("/api/notifications/clear")
async def clear_notifications(_=Depends(require_auth)):
    """Clear all notifications."""
    _notifications.clear()
    return {"cleared": True}


# Serve frontend static files in production
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8888)))
