#!/bin/bash
# LOLM TPU Pod Setup Script
# Runs on ALL workers in a pod simultaneously.
#
# Usage (from local machine):
#   gcloud compute tpus tpu-vm ssh POD_NAME --zone=ZONE --worker=all \
#     -- 'bash -s' < setup_tpu_pod.sh
#
# Or with HF token:
#   gcloud compute tpus tpu-vm ssh POD_NAME --zone=ZONE --worker=all \
#     -- 'HF_TOKEN=hf_xxx bash -s' < setup_tpu_pod.sh

set -euo pipefail

WORKER_ID=${TPU_WORKER_ID:-$(hostname)}
echo "=== LOLM TPU Pod Setup — Worker: $WORKER_ID ==="
echo "Date: $(date)"

# ── 1. System packages ──────────────────────────────────────────────
echo "[1/7] System packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq git tmux htop

# ── 2. Upgrade pip ───────────────────────────────────────────────────
echo "[2/7] Upgrading pip..."
pip install --upgrade pip -q

# ── 3. PyTorch + torch_xla ──────────────────────────────────────────
echo "[3/7] Installing PyTorch + torch_xla..."
# v4 VMs (tpu-vm-pt-2.0) come with pre-installed torch+torch_xla 2.0 — keep those.
# v6e/v5e VMs: install from libtpu-releases.
TXLA_VER=$(python3 -c "import torch_xla; print(torch_xla.__version__)" 2>/dev/null || echo "")
if [ -n "$TXLA_VER" ]; then
    echo "  torch_xla pre-installed: $TXLA_VER — pinning torch to match"
    # Pin torch to exact version matching pre-installed torch_xla (avoids symbol mismatch)
    TORCH_VER=$(echo "$TXLA_VER" | grep -oP '^\d+\.\d+\.\d+')
    pip install "torch==${TORCH_VER}" \
      -f https://storage.googleapis.com/libtpu-releases/index.html \
      -q 2>/dev/null || pip install "torch==${TORCH_VER}" -q 2>/dev/null || true
else
    pip install torch torch_xla[tpu] \
      -f https://storage.googleapis.com/libtpu-releases/index.html \
      -q
fi

# ── 4. LOLM dependencies ────────────────────────────────────────────
echo "[4/7] Installing LOLM dependencies..."
pip install tiktoken>=0.5.0 pyyaml>=6.0 tqdm>=4.65.0 numpy>=1.24.0 datasets>=2.14.0 huggingface_hub -q

# ── 5. HuggingFace token ────────────────────────────────────────────
echo "[5/7] HuggingFace token..."
if [ -n "${HF_TOKEN:-}" ]; then
    echo "export HF_TOKEN=\"$HF_TOKEN\"" >> ~/.bashrc
    echo "  Token set in .bashrc"
else
    echo "  WARNING: No HF_TOKEN provided. Set it before training:"
    echo "    export HF_TOKEN=hf_your_token_here"
fi

# ── 6. Clone/update LOLM repo ───────────────────────────────────────
echo "[6/7] Cloning LOLM..."
REPO_DIR="/home/$USER/Latent"
if [ -d "$REPO_DIR" ]; then
    echo "  Repo exists, pulling latest..."
    cd "$REPO_DIR" && git pull || true
else
    cd "/home/$USER"
    git clone https://github.com/TheArtOfSound/LOLM.git Latent
    cd Latent
fi

# ── 7. Verify ────────────────────────────────────────────────────────
echo "[7/7] Verifying..."
python3 -c "
import torch
import torch_xla
import torch_xla.core.xla_model as xm
try:
    import torch_xla.runtime as xr
    n_devices = len(xr.local_devices())
except ImportError:
    xr = None
    n_devices = 'N/A (torch_xla<2.1)'

device = xm.xla_device()
print(f'  PyTorch: {torch.__version__}')
print(f'  torch_xla: {torch_xla.__version__}')
print(f'  XLA device: {device}')
print(f'  Local devices: {n_devices}')

# Quick matmul test
x = torch.randn(2, 3, device=device)
y = x @ x.T
xm.mark_step()
print(f'  Matmul test: OK ({y.shape})')

# Optimizer test
model = torch.nn.Linear(64, 64).to(device)
opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
loss = model(torch.randn(4, 64, device=device)).sum()
loss.backward()
xm.optimizer_step(opt)
xm.mark_step()
print(f'  Optimizer step: OK')
print(f'  === Worker READY ===')
"

echo ""
echo "Worker $WORKER_ID setup complete."
echo "Launch training with:"
echo "  cd ~/Latent && PJRT_DEVICE=TPU python3 train_tpu_pod.py --config configs/scale/7b_lolm_pod.yaml"
