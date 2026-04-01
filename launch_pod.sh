#!/bin/bash
# Launch LOLM training on a TPU pod slice.
#
# Usage:
#   ./launch_pod.sh POD_NAME ZONE CONFIG [RESUME_PATH]
#
# Examples:
#   ./launch_pod.sh lolm-7b-v4 us-central2-b configs/scale/7b_lolm_pod.yaml
#   ./launch_pod.sh lolm-10b-v6e europe-west4-a configs/scale/10b_lolm_pod.yaml runs/ckpt.pt

set -euo pipefail

POD_NAME="${1:?Usage: $0 POD_NAME ZONE CONFIG [RESUME]}"
ZONE="${2:?Usage: $0 POD_NAME ZONE CONFIG [RESUME]}"
CONFIG="${3:?Usage: $0 POD_NAME ZONE CONFIG [RESUME]}"
RESUME="${4:-}"

echo "=== Launching LOLM Pod Training ==="
echo "  Pod:    $POD_NAME"
echo "  Zone:   $ZONE"
echo "  Config: $CONFIG"
echo "  Resume: ${RESUME:-none}"
echo ""

# Build the training command
TRAIN_CMD="cd ~/Latent && PJRT_DEVICE=TPU"

# Add HF token if set locally
if [ -n "${HF_TOKEN:-}" ]; then
    TRAIN_CMD="$TRAIN_CMD HF_TOKEN=$HF_TOKEN"
fi

TRAIN_CMD="$TRAIN_CMD python3 train_tpu_pod.py --config $CONFIG"

if [ -n "$RESUME" ]; then
    TRAIN_CMD="$TRAIN_CMD --resume $RESUME"
fi

echo "Command: $TRAIN_CMD"
echo ""

# Launch on all workers in tmux sessions
# tmux ensures training survives SSH disconnect
gcloud compute tpus tpu-vm ssh "$POD_NAME" \
    --zone="$ZONE" \
    --worker=all \
    --command="tmux kill-session -t train 2>/dev/null; tmux new-session -d -s train '$TRAIN_CMD 2>&1 | tee ~/train_pod.log'"

echo ""
echo "Training launched on all workers."
echo ""
echo "Monitor:"
echo "  gcloud compute tpus tpu-vm ssh $POD_NAME --zone=$ZONE --worker=0 -- 'tail -f ~/train_pod.log'"
echo ""
echo "Attach to tmux:"
echo "  gcloud compute tpus tpu-vm ssh $POD_NAME --zone=$ZONE --worker=0 -- 'tmux attach -t train'"
