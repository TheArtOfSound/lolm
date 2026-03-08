#!/bin/bash
# LOLM — Vast.ai GPU Setup Script
# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Usage:
#   1. Rent a GPU on Vast.ai (A100 80GB recommended)
#   2. Select image: vastai/base-image:cuda-12.8.1-auto
#   3. SSH in and run:
#      git clone <your-repo-url> /workspace/lolm
#      cd /workspace/lolm
#      bash setup_vastai.sh [300m|1b]
#
# Default: 300m config

set -e

SCALE=${1:-300m}
echo "=========================================="
echo "  LOLM — Latent Order Language Model"
echo "  Setting up ${SCALE} scale training"
echo "=========================================="

# System info
echo ""
echo "System:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "No GPU detected"
python3 --version
echo ""

# Install dependencies
echo "Installing dependencies..."
pip install --no-cache-dir -r requirements-gpu.txt 2>&1 | tail -3
echo ""

# Verify CUDA
python3 -c "
import torch
print(f'PyTorch {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB')
print(f'BF16 support: {torch.cuda.is_bf16_supported()}')
"

# Check for mamba CUDA kernels
python3 -c "
try:
    from mamba_ssm import Mamba
    print('mamba-ssm CUDA kernels: available')
except ImportError:
    print('mamba-ssm CUDA kernels: NOT available (will use pure PyTorch fallback)')
"

echo ""

# Tokenize data
echo "Preparing data..."
python3 prepare_data.py --config configs/scale/${SCALE}.yaml --split train
echo ""

# Count params
echo "Model parameters:"
python3 count_params.py --config configs/scale/${SCALE}.yaml
echo ""

# Create runs directory
mkdir -p runs/${SCALE}

# Start dashboard in background
echo "Starting dashboard on port 8501..."
python3 -u dashboard.py --port 8501 --run-dir runs/${SCALE} &
DASH_PID=$!
echo "Dashboard PID: $DASH_PID"
echo ""

# Optional: start W&B logging
if command -v wandb &> /dev/null; then
    echo "W&B available. Set WANDB_API_KEY to enable logging."
fi

echo "=========================================="
echo "  Ready to train!"
echo ""
echo "  Start training:"
echo "    python3 -u train.py --config configs/scale/${SCALE}.yaml"
echo ""
echo "  Monitor dashboard:"
echo "    http://localhost:8501"
echo ""
echo "  Resume from checkpoint:"
echo "    python3 -u train.py --config configs/scale/${SCALE}.yaml --resume runs/${SCALE}/ckpt_XXXXX.pt"
echo ""
echo "  Run ablations:"
echo "    python3 ablation.py"
echo "=========================================="
