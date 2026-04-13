"""WebSocket log streaming via direct SSH tail -f to TPU VM."""

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from training import parse_log_line, get_tpu_ips, SSH_KEY, SSH_USER, SSH_OPTS

router = APIRouter()


@router.websocket("/ws/logs")
async def websocket_log_stream(websocket: WebSocket):
    """Stream training log in real-time via WebSocket.

    Client sends: {"tpu_name": "lolm-7b"}
    Server streams: {"type": "log"|"step", "line": "...", "metrics": {...}}
    """
    await websocket.accept()

    try:
        init_data = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except Exception:
        await websocket.close(code=1008, reason="Expected TPU info")
        return

    tpu_name = init_data.get("tpu_name", "lolm-7b")
    zone = init_data.get("zone", "us-central2-b")

    # Get worker 0 IP
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        await websocket.send_json({"type": "error", "message": f"No IPs for {tpu_name}"})
        await websocket.close()
        return

    ip = ips[0]
    cmd = ["ssh"] + SSH_OPTS.split() + [f"{SSH_USER}@{ip}", "tail -f ~/train_pod.log"]

    proc: Optional[asyncio.subprocess.Process] = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await websocket.send_json({"type": "connected", "tpu": tpu_name, "ip": ip})

        while True:
            line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=300)
            if not line_bytes:
                await websocket.send_json({"type": "disconnected", "reason": "SSH ended"})
                break

            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue

            metrics = parse_log_line(line)
            msg = {"type": "step" if metrics else "log", "line": line}
            if metrics:
                msg["metrics"] = metrics
            await websocket.send_json(msg)

            # Feed log line into notification system (lazy import to avoid circular)
            try:
                from main import parse_notifications_from_log
                parse_notifications_from_log(line)
            except Exception:
                pass

    except WebSocketDisconnect:
        pass
    except asyncio.TimeoutError:
        try:
            await websocket.send_json({"type": "timeout"})
        except Exception:
            pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
