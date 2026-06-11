#!/usr/bin/env bash
# Serve the 4B NFET agent from this machine as the public "lab line".
#
# Starts the demo server on 127.0.0.1:7867 (Qwen3-4B on MPS, trained graft +
# controller) and keeps a reverse SSH tunnel open to the web box, where nginx
# exposes it as https://lolm.imagineqira.com/api/demo4b/. When this machine
# sleeps or the tunnel drops, the public page simply greys out the 4B option —
# the 0.6B box line is unaffected.
#
# Usage:  ./scripts/serve_4b_public.sh            # foreground, Ctrl-C stops both
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-7867}"
REMOTE="${REMOTE:-autohustle-aws}"

echo "[lab-line] starting 4B demo server on 127.0.0.1:${PORT}..."
LOCAL_UI_ENABLE_MPS=1 \
DEMO_PROFILE=qwen3_4b_lab \
DEMO_DEVICE=mps \
DEMO_GRAFT_CKPT=runs/nfet_controller/live_qwen4b.pt \
DEMO_RATE_PER_HOUR="${DEMO_RATE_PER_HOUR:-3}" \
DEMO_MAX_RUN_SECONDS="${DEMO_MAX_RUN_SECONDS:-420}" \
HOST=127.0.0.1 PORT="${PORT}" \
PYTHONPATH=. .venv/bin/python local_ui/server_public_demo.py &
SERVER_PID=$!
trap 'echo "[lab-line] stopping"; kill ${SERVER_PID} 2>/dev/null || true; exit 0' INT TERM

echo "[lab-line] holding reverse tunnel ${REMOTE}:${PORT} -> localhost:${PORT} (auto-reconnect)"
while kill -0 ${SERVER_PID} 2>/dev/null; do
  ssh -N \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -R "127.0.0.1:${PORT}:127.0.0.1:${PORT}" \
    "${REMOTE}" || true
  echo "[lab-line] tunnel dropped; retrying in 5s"
  sleep 5
done
