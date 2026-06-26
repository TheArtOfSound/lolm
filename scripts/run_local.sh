#!/usr/bin/env bash
# Run LOLM 100% on YOUR machine — sovereign mode, zero external calls.
#
#   1. install a local model server (once):  brew install ollama  (or get llama.cpp / LM Studio)
#   2. pull a capable open model (once):      ollama pull qwen2.5:7b   # or llama3.1:8b, etc.
#   3. run this:                              scripts/run_local.sh
#   4. open:                                  http://127.0.0.1:7870/index.html
#
# It refuses the cloud entirely (LOLM_SOVEREIGN=1), generates from your local model,
# runs the NFET uncertainty control on the Apple GPU (MPS), and has NO budgets.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${LOLM_LOCAL_MODEL:-qwen2.5:7b}"        # any model your machine can run
PORT="${PORT:-7870}"
PY="${PY:-.venv/bin/python}"
# Apple Silicon → mps (GPU); otherwise cpu. Override with DEMO_DEVICE.
DEVICE="${DEMO_DEVICE:-$([[ "$(uname -m)" == "arm64" ]] && echo mps || echo cpu)}"

echo "LOLM sovereign — model=$MODEL device=$DEVICE port=$PORT"
echo "  (cloud is OFF; nothing leaves this machine)"

# unset any cloud credentials so this process is provably local
env -u WORKERS_AI_URL -u WORKERS_AI_SECRET -u BRAIN_URL -u BRAIN_SECRET \
  LOLM_SOVEREIGN=1 \
  LOLM_LOCAL_MODEL="$MODEL" \
  LOLM_LOCAL_API="${LOLM_LOCAL_API:-ollama}" \
  LOLM_LOCAL_URL="${LOLM_LOCAL_URL:-http://127.0.0.1:11434}" \
  DEMO_DEVICE="$DEVICE" \
  DEMO_RATE_PER_HOUR=0 \
  PORT="$PORT" DEMO_HOST="${DEMO_HOST:-127.0.0.1}" \
  "$PY" -m local_ui.server_public_demo
