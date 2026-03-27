#!/bin/bash
# LOLM TPU VM Setup Script
# Usage: gcloud compute tpus tpu-vm ssh lolm-v3 --zone=us-east1-d -- 'bash -s' < setup_tpu.sh
#    or: SSH in first, then: bash setup_tpu.sh
#
# Prerequisites:
#   gcloud compute tpus tpu-vm create lolm-v3 \
#     --accelerator-type=v3-8 \
#     --version=tpu-ubuntu2204-base \
#     --zone=us-east1-d \
#     --project=lolm-tpu-research

set -euo pipefail

echo "=== LOLM TPU VM Setup ==="
echo "Date: $(date)"
echo "Host: $(hostname)"

# ── 1. System packages ──────────────────────────────────────────────
echo ""
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq git tmux htop

# ── 2. Python environment ───────────────────────────────────────────
echo ""
echo "[2/6] Setting up Python environment..."
pip install --upgrade pip

# ── 3. PyTorch + torch_xla (TPU) ────────────────────────────────────
echo ""
echo "[3/6] Installing PyTorch + torch_xla..."
# Install matching torch + torch_xla versions for TPU
pip install torch torch_xla[tpu] \
  -f https://storage.googleapis.com/libtpu-releases/index.html

# ── 4. LOLM dependencies ────────────────────────────────────────────
echo ""
echo "[4/6] Installing LOLM dependencies..."
pip install tiktoken>=0.5.0 pyyaml>=6.0 tqdm>=4.65.0 numpy>=1.24.0 datasets>=2.14.0

# ── 5. Clone LOLM repo ──────────────────────────────────────────────
echo ""
echo "[5/6] Cloning LOLM..."
if [ -d "/home/$USER/lolm" ]; then
    echo "  LOLM directory exists, pulling latest..."
    cd "/home/$USER/lolm" && git pull
else
    cd "/home/$USER"
    git clone https://github.com/TheArtOfSound/LOLM.git lolm
    cd lolm
fi

# ── 6. Verify setup ─────────────────────────────────────────────────
echo ""
echo "[6/6] Verifying installation..."
python3 -c "
import torch
import torch_xla
import torch_xla.core.xla_model as xm

device = xm.xla_device()
print(f'PyTorch version: {torch.__version__}')
print(f'torch_xla version: {torch_xla.__version__}')
print(f'XLA device: {device}')
print(f'Device type: {xm.xla_device_hw(device)}')

# Quick tensor test
x = torch.randn(2, 3, device=device)
y = x @ x.T
print(f'Matrix multiply test: {y.shape} on {y.device}')
print()
print('=== TPU READY ===')
"

echo ""
echo "============================================"
echo "  Setup complete!"
echo ""
echo "  Smoke test (304M, ~2 min):"
echo "    cd ~/lolm && python train.py --config configs/scale/300m_tpu.yaml"
echo ""
echo "  Full run (1.57B):"
echo "    cd ~/lolm && python train.py --config configs/scale/1b_tpu.yaml"
echo ""
echo "  Resume from H200 checkpoint:"
echo "    gsutil cp gs://YOUR-BUCKET/ckpt_20000.pt runs/1b_tpu/"
echo "    python train.py --config configs/scale/1b_tpu.yaml --resume runs/1b_tpu/ckpt_20000.pt"
echo ""
echo "  TIP: Run in tmux so training survives SSH disconnect:"
echo "    tmux new -s train"
echo "    python train.py --config configs/scale/1b_tpu.yaml"
echo "    # Ctrl-B, D to detach. tmux attach -t train to reconnect."
echo "============================================"
