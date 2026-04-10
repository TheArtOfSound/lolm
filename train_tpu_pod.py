# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Licensed under the LOLM Community License Agreement, Version 1.0
# (the "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License in the
# LICENSE file at the root of this repository.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for specific terms and conditions.

"""Multi-host TPU pod training for LOLM via PyTorch XLA FSDP.

Wraps Bryan's LOLM model with FSDP for distributed training across
TPU pod slices (v4-32, v6e-64, v5e-64, etc.). Does NOT modify any
model architecture, loss functions, or data pipeline internals.

Based on train_tpu.py with these additions:
  - FSDP wrapping: shards params + grads + optimizer across all chips
  - Multi-host coordination via PJRT (automatic peer discovery)
  - Rank-aware data sharding (each chip sees different documents)
  - GCS checkpoint support for cross-host persistence
  - MpDeviceLoader for automatic mark_step management

Launch on a TPU pod (all workers simultaneously):
  gcloud compute tpus tpu-vm ssh POD_NAME --zone=ZONE --worker=all \\
    --command="cd ~/Latent && PJRT_DEVICE=TPU python3 train_tpu_pod.py \\
              --config configs/scale/7b_lolm_pod.yaml"

Resume from checkpoint:
  ... --command="... python3 train_tpu_pod.py --config ... --resume gs://bucket/ckpt.pt"

The core mathematics are IDENTICAL to train.py / train_tpu.py:
  - Same SSM recurrence: h[t] = A_bar[t] * h[t-1] + Bx[t]
  - Same 7 training losses with same lambda weights
  - Same gradient isolation for regime codes
  - Same Gumbel-Softmax regime selection
  - Same CPC InfoNCE contrastive learning
  - Same cosine LR schedule with warmup
"""

import argparse
import contextlib
import functools
import json
import math
import os
import subprocess
import time
from pathlib import Path

import torch
import torch.nn as nn

# torch_xla imports
import torch_xla
import torch_xla.core.xla_model as xm
import torch_xla.debug.metrics as met
import torch_xla.distributed.parallel_loader as pl
import torch_xla.distributed.xla_multiprocessing as xmp
try:
    import torch_xla.runtime as xr
except ImportError:
    xr = None  # torch_xla < 2.1 — xr only needed for --use-spawn local mode

# FSDP imports
from torch_xla.distributed.fsdp import XlaFullyShardedDataParallel as FSDP
from torch_xla.distributed.fsdp.wrap import transformer_auto_wrap_policy

from lolm.config import load_config
from lolm.decoder import DecoderBlock
from lolm.losses import LOLMLoss
from lolm.model import LOLM
from lolm.ssm import SelectiveSSMLayer


# ---------------------------------------------------------------------------
# GCS checkpoint helpers
# ---------------------------------------------------------------------------

def gcs_upload(local_path: str, gcs_path: str) -> bool:
    """Upload a file to GCS. Returns True on success, False on failure."""
    try:
        subprocess.run(
            ["gsutil", "-q", "cp", local_path, gcs_path],
            check=True, timeout=600,
        )
        return True
    except Exception as e:
        print(f"[GCS] Upload failed ({local_path} → {gcs_path}): {e}", flush=True)
        return False


def gcs_download(gcs_path: str, local_path: str) -> bool:
    """Download a file from GCS. Returns True on success, False on failure."""
    try:
        subprocess.run(
            ["gsutil", "-q", "cp", gcs_path, local_path],
            check=True, timeout=600,
        )
        return True
    except Exception as e:
        return False


def gcs_read_text(gcs_path: str) -> str:
    """Read a small text file from GCS. Returns '' on failure."""
    try:
        result = subprocess.run(
            ["gsutil", "cat", gcs_path],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def gcs_find_latest(gcs_dir: str) -> str:
    """Return the GCS path of the latest checkpoint, or '' if none exists.

    Reads <gcs_dir>/latest.txt which contains the checkpoint filename.
    """
    latest = gcs_read_text(f"{gcs_dir.rstrip('/')}/latest.txt")
    if latest:
        return f"{gcs_dir.rstrip('/')}/{latest}"
    return ""


# ---------------------------------------------------------------------------
# LR + temperature schedules (identical to train.py / train_tpu.py)
# ---------------------------------------------------------------------------

def get_lr(step: int, warmup: int, max_steps: int, max_lr: float) -> float:
    """Cosine schedule with linear warmup."""
    if step < warmup:
        return max_lr * step / warmup
    decay_ratio = (step - warmup) / max(1, max_steps - warmup)
    coeff = 0.5 * (1.0 + math.cos(math.pi * decay_ratio))
    return max_lr * max(coeff, 0.1)  # 10% floor


def get_regime_temperature(step: int, cfg) -> float:
    """Anneal Gumbel-Softmax temperature."""
    if step >= cfg.model.regime.temp_anneal_steps:
        return cfg.model.regime.temp_end
    ratio = step / cfg.model.regime.temp_anneal_steps
    return cfg.model.regime.temp_start + ratio * (
        cfg.model.regime.temp_end - cfg.model.regime.temp_start
    )


# ---------------------------------------------------------------------------
# FSDP wrapping — wraps the model WITHOUT modifying it
# ---------------------------------------------------------------------------

def wrap_with_fsdp(model: nn.Module) -> nn.Module:
    """Wrap decoder + LM head + large replicated modules with XLA FSDP.

    Strategy for fitting 5.8B LOLM in 32GB HBM per chip on v4-32:

    FSDP-sharded (params + optimizer + grads distributed across 16 chips):
      - model.decoder (5.2B params) — the dominant cost
      - model.lm_head (206M params) — untied from tok_emb, wrapped separately

    Replicated (full copy on every chip):
      - SSM layers (~186M) — scan carry state can't be sharded
      - Memory banks (~155M) — slot attention is per-chip
      - Regime (~1M), Gate (~136M), Fusion projections (~51M)
      Total replicated: ~530M × 10B (bf16 params + fp32 Adam) ≈ 5.3GB/chip

    Memory budget per chip (v4-32, 32GB HBM):
      Decoder FSDP shard:  5.2B / 16 × 12B (param+adam+grad) ≈  3.9GB
      LM head FSDP shard:  206M / 16 × 12B                   ≈  155MB
      Replicated params+opt:                                  ≈  5.3GB
      FSDP all-gather buffer (1 DecoderBlock at a time):      ≈  0.3GB
      Activations (with grad checkpointing):                  ≈  2-4GB
      XLA compiler overhead:                                  ≈  2-4GB
      Total:                                                  ≈ 14-18GB — fits in 32GB
    """
    # Untie LM head weight from tok_emb — XlaFSDP can't handle parameter
    # aliasing across FSDP boundary (decoder inside, lm_head outside).
    model.lm_head.weight = nn.Parameter(model.decoder.tok_emb.weight.data.clone())

    auto_wrap_policy = functools.partial(
        transformer_auto_wrap_policy,
        transformer_layer_cls={DecoderBlock},
    )

    # XLA-compatible gradient checkpointing: wrap each DecoderBlock with
    # checkpoint_module before FSDP wrapping. This uses XLA optimization
    # barriers to prevent the compiler from fusing across checkpoint
    # boundaries, unlike torch.utils.checkpoint which XLA silently ignores.
    try:
        from torch_xla.distributed.fsdp import checkpoint_module
        def _ckpt_wrapper(module, **kwargs):
            return FSDP(checkpoint_module(module), **kwargs)
        auto_wrapper_callable = _ckpt_wrapper
        print("FSDP: using XLA gradient checkpointing per DecoderBlock", flush=True)
    except ImportError:
        auto_wrapper_callable = None
        print("FSDP: no XLA checkpoint_module available, skipping grad checkpointing", flush=True)

    # 1. FSDP-wrap the decoder (5.2B params)
    model.decoder = FSDP(
        model.decoder,
        auto_wrap_policy=auto_wrap_policy,
        auto_wrapper_callable=auto_wrapper_callable,
        compute_dtype=torch.bfloat16,
        buffer_dtype=torch.bfloat16,
        flatten_parameters=True,   # MUST be True: tok_emb is [50257, 4096] and 50257 is
                                   # prime (GPT-2 intentional), so 50257 % world_size != 0
                                   # for any world_size > 1. flatten_parameters=False shards
                                   # dim-0 → unequal shards → XLA all-gather fatal kill.
                                   # flatten_parameters=True flattens to 205,852,672 elements
                                   # which is divisible by any power-of-2 world_size.
        pin_layout_in_collective_ops=True,
    )

    # 2. FSDP-wrap the LM head (206M params — saves 2GB/chip vs replicated)
    model.lm_head = FSDP(
        model.lm_head,
        compute_dtype=torch.bfloat16,
        buffer_dtype=torch.bfloat16,
        flatten_parameters=True,
        pin_layout_in_collective_ops=True,
    )
    print("FSDP: wrapped lm_head (saves ~2GB/chip)", flush=True)

    # 3. FSDP-wrap SSM projection layers (170M params — saves ~1.7GB/chip)
    # The scan itself can't be FSDP'd (carry state is per-device), but the
    # large linear projections (in_proj, out_proj, dt_proj) CAN be sharded.
    if hasattr(model, 'ssm') and model.ssm is not None:
        for i, layer in enumerate(model.ssm.layers):
            if hasattr(layer, 'in_proj'):
                layer.in_proj = FSDP(layer.in_proj,
                    compute_dtype=torch.bfloat16, buffer_dtype=torch.bfloat16,
                    flatten_parameters=True, pin_layout_in_collective_ops=True)
            if hasattr(layer, 'out_proj'):
                layer.out_proj = FSDP(layer.out_proj,
                    compute_dtype=torch.bfloat16, buffer_dtype=torch.bfloat16,
                    flatten_parameters=True, pin_layout_in_collective_ops=True)
            if hasattr(layer, 'dt_proj'):
                layer.dt_proj = FSDP(layer.dt_proj,
                    compute_dtype=torch.bfloat16, buffer_dtype=torch.bfloat16,
                    flatten_parameters=True, pin_layout_in_collective_ops=True)
        print(f"FSDP: wrapped SSM projections ({len(model.ssm.layers)} layers, saves ~1.7GB/chip)", flush=True)

    return model


def sync_replicated_grads(model: nn.Module, loss_fn: nn.Module,
                          world_size: int) -> None:
    """Allreduce gradients for params NOT covered by FSDP.

    The decoder and lm_head are FSDP-wrapped so their grads are handled by
    reduce-scatter. All other params (SSM, memory, regime, gate, fusion
    projections, CPC projections) are replicated and need explicit gradient sync.
    """
    # Collect grads for replicated-only params (skip all FSDP-wrapped modules)
    fsdp_prefixes = ('decoder.', 'lm_head.')
    # SSM projection layers are also FSDP-wrapped
    if hasattr(model, 'ssm') and model.ssm is not None:
        for i, layer in enumerate(model.ssm.layers):
            for attr in ('in_proj', 'out_proj', 'dt_proj'):
                if hasattr(layer, attr) and isinstance(getattr(layer, attr), FSDP):
                    fsdp_prefixes = fsdp_prefixes + (f'ssm.layers.{i}.{attr}.',)

    grads = []
    for name, param in model.named_parameters():
        if not any(name.startswith(p) for p in fsdp_prefixes) and param.grad is not None:
            grads.append(param.grad)
    for param in loss_fn.parameters():
        if param.grad is not None:
            grads.append(param.grad)
    if grads:
        xm.all_reduce(xm.REDUCE_SUM, grads, scale=1.0 / world_size)


# ---------------------------------------------------------------------------
# Main training function — runs on every chip
# ---------------------------------------------------------------------------

def train_fn(index, config_path: str, resume_from: str = None, gcs_path: str = None):
    """Training function executed on each TPU chip in the pod."""

    # --- Distributed setup ---
    device = xm.xla_device()
    ordinal = xm.get_ordinal()
    world_size = xm.xrt_world_size()
    is_master = xm.is_master_ordinal()

    # Give each rank its own HF datasets cache to prevent filelock EBADF
    # when 4+ processes simultaneously access the same lockfile on one host.
    import os as _os
    _os.environ['HF_DATASETS_CACHE'] = f'/tmp/hf_cache_rank_{ordinal}'
    _os.makedirs(f'/tmp/hf_cache_rank_{ordinal}', exist_ok=True)

    # Set a fresh asyncio event loop for this rank. Do NOT close the old loop
    # as that can invalidate XLA's internal FDs. Just register a new one so
    # fsspec/aiohttp creates sessions bound to a clean loop.
    import asyncio as _asyncio
    _asyncio.set_event_loop(_asyncio.new_event_loop())

    def log(msg):
        if is_master:
            print(msg, flush=True)

    log(f"LOLM Pod Training — {world_size} chips")
    log(f"XLA device: {device}")

    # --- Config ---
    cfg = load_config(config_path)
    tc = cfg.training

    # Environment variable overrides for dashboard-launched runs
    _env_dataset = os.environ.get("LOLM_DATASET", "")
    if _env_dataset:
        cfg.data.dataset = _env_dataset
        cfg.data.streaming = not _env_dataset.startswith("/")  # local path = not streaming

    accum_steps = tc.grad_accumulation_steps
    effective_batch = tc.batch_size * accum_steps * world_size
    log(f"Config: {config_path}")
    if _env_dataset:
        log(f"Dataset override: {_env_dataset}")
    log(f"Batch: {tc.batch_size} x {accum_steps} accum x {world_size} chips = {effective_batch} effective")

    # GCS auto-resume is handled in __main__ before xmp.spawn (see below)

    # --- Model (Bryan's LOLM, untouched) ---
    model = LOLM(cfg.model)

    if is_master:
        params = model.count_parameters()
        log("Parameters:")
        for k, v in params.items():
            log(f"  {k}: {v:,}")

    # For large models: try FSDP wrapping.
    # If OOM, fall back to single-device mode without FSDP.
    total_params = sum(p.numel() for p in model.parameters())
    use_fsdp = total_params > 2_000_000_000  # FSDP for >2B params

    # XLA device: disable torch.utils.checkpoint (not XLA-compatible in 2.x)
    # The decoder/SSM check _xla_device to skip torch.utils.checkpoint
    model.decoder._xla_device = True
    if hasattr(model, "ssm") and model.ssm is not None:
        model.ssm._xla_device = True

    if use_fsdp:
        log(f"Model has {total_params/1e9:.1f}B params — using FSDP (decoder only)")
        # Wrap only model.decoder with FSDP, then move full model to device.
        # SSM/memory/regime/gate stay replicated (small enough to fit).
        model = wrap_with_fsdp(model)
        model = model.to(device)
        log("FSDP wrapping complete")
        # DEBUG: verify critical parameter shapes after FSDP + .to(device)
        if is_master:
            if hasattr(model, 'regime') and model.regime is not None:
                log(f"DEBUG regime.logit_proj.weight: {model.regime.logit_proj.weight.shape}")
            if hasattr(model, 'ssm') and model.ssm is not None:
                l = model.ssm.layers[0]
                log(f"DEBUG ssm.layers[0].in_proj.weight: {l.in_proj.weight.shape}, A_log: {l.A_log.shape}")
    else:
        log(f"Model has {total_params/1e6:.0f}M params — single-device mode")
        model = model.to(device)

    # --- Loss (Bryan's LOLMLoss, untouched) ---
    loss_fn = LOLMLoss(
        lambda_future=cfg.loss.lambda_future,
        lambda_regime=cfg.loss.lambda_regime,
        lambda_mem=cfg.loss.lambda_mem,
        lambda_manifest=cfg.loss.lambda_manifest,
        future_window=cfg.loss.future_window,
        lambda_balance=cfg.loss.lambda_balance,
        use_load_balance=cfg.loss.use_load_balance,
        lambda_sticky=cfg.loss.lambda_sticky,
        use_cpc=cfg.loss.use_cpc,
        cpc_temperature=cfg.loss.cpc_temperature,
        cpc_max_positions=cfg.loss.cpc_max_positions,
        lambda_changepoint=cfg.loss.lambda_changepoint,
        lambda_competitive=cfg.loss.lambda_competitive,
        cpc_proj_dim=cfg.loss.cpc_proj_dim,
    ).to(device)

    # Eagerly init CPC projections (XLA doesn't like lazy module creation)
    if cfg.loss.cpc_proj_dim > 0:
        loss_fn._init_cpc_proj(cfg.model.d_model, device)
        log(f"CPC projection: d_model={cfg.model.d_model} → d_proj={cfg.loss.cpc_proj_dim}, temp={cfg.loss.cpc_temperature}")

    # --- NFET Adaptive Training Controller ---
    from lolm.nfet_trainer import NFETTrainingController, NFETTrainingConfig
    nfet_config = NFETTrainingConfig(
        enabled=True,
        gate_ridge_target=0.83,
        gate_ridge_warmup=5000,
    )
    nfet_controller = NFETTrainingController(nfet_config, {
        'lambda_future': cfg.loss.lambda_future,
        'lambda_competitive': cfg.loss.lambda_competitive,
        'lambda_regime': cfg.loss.lambda_regime,
    })
    log("NFET adaptive training controller initialized")

    # --- Resume ---
    start_step = 0
    ckpt_optimizer_state = None
    if resume_from:
        log(f"Loading checkpoint: {resume_from}")
        ckpt = torch.load(resume_from, map_location="cpu", weights_only=False)
        # FSDP: load into unwrapped model then re-wrap, or load sharded
        # For simplicity, load full state dict (consolidated checkpoint)
        model.load_state_dict(ckpt["model"])
        start_step = ckpt["step"]
        ckpt_optimizer_state = ckpt.get("optimizer")
        if "loss_fn" in ckpt:
            saved_state = ckpt["loss_fn"]
            current_state = loss_fn.state_dict()
            compatible_state = {}
            for k, v in saved_state.items():
                if k in current_state and v.shape == current_state[k].shape:
                    compatible_state[k] = v
            loss_fn.load_state_dict(compatible_state, strict=False)
        log(f"Resumed from step {start_step}")
        del ckpt

    # --- Optimizer ---
    # Split into two groups to save HBM on replicated params:
    #   - FSDP params (decoder + lm_head): AdamW — optimizer states are sharded
    #   - Replicated params (SSM, memory, gate, fusion, CPC): SGD with momentum
    #     SGD uses 4B/param (momentum only) vs AdamW's 8B/param (momentum+variance)
    #     For ~530M replicated params this saves ~2.1GB HBM per chip
    fsdp_params = []
    replicated_params = []
    for name, param in model.named_parameters():
        if name.startswith('decoder.') or name.startswith('lm_head.'):
            fsdp_params.append(param)
        else:
            replicated_params.append(param)
    # CPC projection params in loss_fn are also replicated
    replicated_params.extend(list(loss_fn.parameters()))

    if use_fsdp and replicated_params:
        optimizer = torch.optim.AdamW(
            fsdp_params,
            lr=tc.lr,
            weight_decay=tc.weight_decay,
            betas=(tc.beta1, tc.beta2),
        )
        optimizer_replicated = torch.optim.SGD(
            replicated_params,
            lr=tc.lr,
            weight_decay=tc.weight_decay,
            momentum=0.9,
        )
        log(f"Optimizer: AdamW for {sum(p.numel() for p in fsdp_params)/1e6:.0f}M FSDP params, "
            f"SGD for {sum(p.numel() for p in replicated_params)/1e6:.0f}M replicated params "
            f"(saves ~2GB HBM/chip)")
    else:
        optimizer = torch.optim.AdamW(
            list(model.parameters()) + list(loss_fn.parameters()),
            lr=tc.lr,
            weight_decay=tc.weight_decay,
            betas=(tc.beta1, tc.beta2),
        )
        optimizer_replicated = None

    if ckpt_optimizer_state is not None:
        optimizer.load_state_dict(ckpt_optimizer_state)
        del ckpt_optimizer_state

    # --- Data (rank-aware sharding) ---
    def make_loader():
        """Create a fresh loader — called on init and on data errors."""
        if cfg.data.streaming:
            from lolm.data_streaming import get_streaming_dataloader
            _loader = get_streaming_dataloader(
                cfg.data.dataset, tc.seq_len, tc.batch_size,
                tokenizer_name=cfg.data.tokenizer,
                num_workers=0,  # 0 avoids multi-connection HF rate limiting on TPU
                dataset_config=getattr(cfg.data, 'dataset_config', None) or None,
                rank=ordinal,
                world_size=world_size,
            )
        else:
            from lolm.data import get_dataloader
            _loader = get_dataloader(
                cfg.data.dataset, cfg.data.cache_dir, tc.seq_len, tc.batch_size
            )
        return pl.MpDeviceLoader(_loader, device)

    log("Loading data...")
    mp_loader = make_loader()
    if cfg.data.streaming:
        log(f"Streaming from: {cfg.data.dataset} (shard {ordinal}/{world_size})")

    # --- Output directory ---
    config_name = Path(config_path).stem
    out_dir = Path("runs") / config_name
    if is_master:
        out_dir.mkdir(parents=True, exist_ok=True)

    # --- AMP context ---
    train_dtype = torch.bfloat16 if tc.dtype in ("bfloat16", "float16") else torch.float32
    if train_dtype != torch.float32:
        amp_ctx = torch.amp.autocast(device_type="xla", dtype=train_dtype)
        log(f"AMP: {tc.dtype} on TPU (native, no GradScaler)")
    else:
        amp_ctx = contextlib.nullcontext()

    # --- Training loop ---
    model.train()
    log_losses = {}
    t0 = time.time()
    consecutive_nan = 0

    log(f"\n{'='*60}")
    log(f"Starting LOLM Pod Training")
    log(f"  Steps: {start_step} → {tc.max_steps}")
    log(f"  Global batch: {effective_batch}")
    log(f"  Dtype: {train_dtype}")
    log(f"  Chips: {world_size}")
    log(f"{'='*60}\n")

    data_iter = iter(mp_loader)

    for step in range(start_step, tc.max_steps):
        # LR schedule + NFET ES-modulated dampening
        lr = get_lr(step, tc.warmup_steps, tc.max_steps, tc.lr)
        lr = lr * nfet_controller.get_lr_multiplier()
        for pg in optimizer.param_groups:
            pg["lr"] = lr
        if optimizer_replicated is not None:
            for pg in optimizer_replicated.param_groups:
                pg["lr"] = lr

        # Regime temperature
        temp = get_regime_temperature(step, cfg)

        # --- Gradient accumulation loop ---
        optimizer.zero_grad()
        if optimizer_replicated is not None:
            optimizer_replicated.zero_grad()
        accum_loss_total = 0.0
        accum_components = {}
        step_had_nan = False

        for micro_step in range(accum_steps):
            # Get batch (MpDeviceLoader already puts data on device)
            for _attempt in range(5):
                try:
                    x, y = next(data_iter)
                    break
                except StopIteration:
                    mp_loader = make_loader()
                    data_iter = iter(mp_loader)
                except Exception as _de:
                    log(f"[rank {ordinal}] Data fetch error (attempt {_attempt+1}/5): {_de}, rebuilding loader")
                    import time as _time; _time.sleep(2 * (_attempt + 1))
                    mp_loader = make_loader()
                    data_iter = iter(mp_loader)
            else:
                x, y = next(data_iter)  # final attempt, crash if still broken

            # NFET: apply adaptive lambdas to loss function
            adapted = nfet_controller.get_adaptive_lambdas()
            loss_fn.lambda_future = adapted.get('lambda_future', loss_fn.lambda_future)
            loss_fn.lambda_competitive = adapted.get('lambda_competitive', loss_fn.lambda_competitive)
            loss_fn.lambda_regime = adapted.get('lambda_regime', loss_fn.lambda_regime)

            # NFET: regime diversity boost
            loss_fn.lambda_regime *= nfet_controller.get_regime_boost()

            # NFET: pause aux losses during gate phase transitions
            if nfet_controller.should_pause_aux_losses():
                loss_fn.lambda_changepoint = 0.0
                loss_fn.lambda_regime = 0.0
                loss_fn.lambda_competitive = 0.0
                loss_fn.lambda_manifest = 0.0
                loss_fn.lambda_mem = 0.0

            # Forward with AMP
            with amp_ctx:
                out = model(x, regime_temperature=temp)
                total_loss, components = loss_fn(
                    logits=out.logits, targets=y,
                    z=out.z, h=out.h,
                    regime_probs=out.regime_probs,
                    regime_indices=out.regime_indices,
                    mem_read=out.mem_read,
                    mem_attn=out.mem_attn,
                    gate_values=out.gate_values,
                )

                # NFET: add gate ridge regularizer to total loss
                if out.gate_values is not None:
                    ridge_loss = nfet_controller.gate_ridge_loss(out.gate_values)
                    total_loss = total_loss + ridge_loss

                scaled_loss = total_loss / accum_steps

            # Backward
            scaled_loss.backward()

            # components dict values are already Python floats (.item()
            # called inside LOLMLoss.forward). Accumulate without blocking.
            accum_loss_total += components.get('loss_total', 0)
            for k, v in components.items():
                accum_components[k] = accum_components.get(k, 0.0) + v / accum_steps

        if step_had_nan:
            optimizer.zero_grad()
            if optimizer_replicated is not None:
                optimizer_replicated.zero_grad()
            xm.mark_step()
            consecutive_nan += 1
            if consecutive_nan >= 100:
                log("[NaN FATAL] 100+ consecutive NaN steps. Saving emergency checkpoint.")
                if is_master:
                    xm.save({
                        "step": step + 1, "model": model.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "loss_fn": loss_fn.state_dict(),
                        "config": config_path,
                    }, str(out_dir / f"ckpt_emergency_{step+1}.pt"))
                break
            continue
        consecutive_nan = 0

        # Sync gradients for replicated params (SSM, memory, regime, gate,
        # fusion projections, lm_head, CPC). Decoder grads are handled by
        # FSDP reduce-scatter; everything else needs explicit allreduce.
        if use_fsdp and world_size > 1:
            sync_replicated_grads(model, loss_fn, world_size)

        # Gradient clipping: clip non-decoder (replicated) params only.
        # XlaFSDP.clip_grad_norm_ is unreliable across chip generations and
        # mixing FSDP sharded grads with full grads produces wrong norm estimates.
        # Decoder grads are implicitly bounded by FSDP reduce-scatter + Adam;
        # replicated params need explicit clipping to prevent NaN.
        if use_fsdp:
            replicated_params = [
                p for name, p in model.named_parameters()
                if not name.startswith('decoder.') and p.grad is not None
            ]
            if replicated_params:
                torch.nn.utils.clip_grad_norm_(replicated_params, tc.grad_clip)
        else:
            torch.nn.utils.clip_grad_norm_(list(model.parameters()), tc.grad_clip)
        cpc_params = list(loss_fn.parameters())
        if cpc_params:
            torch.nn.utils.clip_grad_norm_(cpc_params, tc.grad_clip)

        # Optimizer step. Do NOT use xm.optimizer_step() with FSDP — it does
        # an extra allreduce on ALL gradients, but FSDP already reduce-scattered
        # the decoder gradients. Double-reducing corrupts them. Instead, call
        # optimizer.step() directly and follow with mark_step() to execute.
        optimizer.step()
        if optimizer_replicated is not None:
            optimizer_replicated.step()
        xm.mark_step()

        # Accumulate logs
        for k, v in accum_components.items():
            log_losses[k] = log_losses.get(k, 0.0) + v

        # --- Logging (master only) ---
        if (step + 1) % tc.log_interval == 0:
            dt = time.time() - t0
            avg = {k: v / tc.log_interval for k, v in log_losses.items()}
            ppl = math.exp(min(avg.get("loss_tok", 20), 20))
            # Gate and regime — only materialize at log boundaries (every
            # log_interval steps). This is OK because it's infrequent.
            gate_msg = ""
            if out.gate_values is not None:
                gate_msg = f" | gate={out.gate_values.mean().item():.3f}"
            regime_msg = ""
            if out.regime_indices is not None:
                n_unique = out.regime_indices.unique().numel()
                regime_msg = f" | regimes={n_unique}"

            extra_losses = ""
            for lname, lkey in [
                ("chg", "loss_changepoint"), ("comp", "loss_competitive"),
                ("reg", "loss_regime"), ("mem", "loss_mem"), ("man", "loss_manifest"),
            ]:
                val = avg.get(lkey, 0.0)
                if abs(val) > 1e-8:
                    extra_losses += f" | {lname}={val:.4f}"

            tokens_per_step = effective_batch * tc.seq_len
            total_tokens = (step + 1) * tokens_per_step

            # NFET diagnostics
            nfet_diags = nfet_controller.get_diagnostics()
            nfet_msg = f" | ES={nfet_diags['nfet/es']:.3f} [{nfet_diags['nfet/phase']}]"

            log(
                f"step {step+1:>6d} | loss {avg.get('loss_total', 0):.4f} | "
                f"tok {avg.get('loss_tok', 0):.4f} | ppl {ppl:.1f} | "
                f"fut {avg.get('loss_future', 0):.4f} | lr {lr:.2e} | "
                f"{tc.log_interval/dt:.1f} steps/s | "
                f"{total_tokens/1e9:.2f}B tok"
                f"{gate_msg}{regime_msg}{extra_losses}{nfet_msg}"
            )
            log_losses = {}
            t0 = time.time()

            # NFET alerts
            alert = nfet_controller.should_alert()
            if alert:
                log(f"  {alert}")

            # Save log (master only)
            if is_master:
                log_entry = {"step": step + 1, **avg, "lr": lr, "temp": temp,
                             "world_size": world_size, "tokens": total_tokens}
                if out.gate_values is not None:
                    log_entry["gate_mean"] = out.gate_values.mean().item()
                if out.regime_indices is not None:
                    log_entry["regime_unique"] = out.regime_indices.unique().numel()
                log_entry.update(nfet_diags)
                with open(out_dir / "log.jsonl", "a") as f:
                    f.write(json.dumps(log_entry) + "\n")

        # --- Gradient diagnostic (every 2000 steps, master only) ---
        if (step + 1) % 2000 == 0 and is_master:
            if out.regime_indices is not None:
                hist = torch.bincount(out.regime_indices.view(-1), minlength=cfg.model.regime.n_codes)
                total = hist.sum().item()
                top5 = hist.topk(min(5, len(hist)))
                hist_str = " ".join(f"c{top5.indices[i]}:{top5.values[i].item()}/{total}" for i in range(len(top5.indices)))
                entropy = -(hist.float() / total * (hist.float() / total + 1e-10).log()).sum().item()
                max_entropy = torch.tensor(float(cfg.model.regime.n_codes)).log().item()
                log(f"  [regime hist step {step+1}] top5: {hist_str} | usage_entropy={entropy:.3f}/{max_entropy:.3f}")

        # --- Save checkpoint (master only, XLA-aware) ---
        if (step + 1) % tc.save_interval == 0:
            ckpt_name = f"ckpt_{step+1}.pt"
            ckpt_path = out_dir / ckpt_name
            if is_master:
                xm.save({
                    "step": step + 1,
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "loss_fn": loss_fn.state_dict(),
                    "config": config_path,
                    "world_size": world_size,
                }, str(ckpt_path))
                log(f"Saved checkpoint: {ckpt_path}")
                # Auto-cleanup: keep only latest 2 local checkpoints to prevent disk full
                existing_ckpts = sorted(out_dir.glob("ckpt_*.pt"), key=lambda p: p.stat().st_mtime)
                while len(existing_ckpts) > 2:
                    old = existing_ckpts.pop(0)
                    try:
                        old.unlink()
                        log(f"Deleted old checkpoint: {old.name} (keeping latest 2)")
                    except Exception:
                        pass
                if gcs_path:
                    gcs_dir = gcs_path.rstrip("/")
                    if gcs_upload(str(ckpt_path), f"{gcs_dir}/{ckpt_name}"):
                        # Write latest.txt so auto-resume can find it
                        latest_local = "/tmp/latest.txt"
                        with open(latest_local, "w") as f:
                            f.write(ckpt_name)
                        gcs_upload(latest_local, f"{gcs_dir}/latest.txt")
                        log(f"GCS: uploaded {ckpt_name}")
                        # Remove local checkpoint to keep disk from filling up
                        try:
                            ckpt_path.unlink()
                            log(f"GCS: removed local {ckpt_name} (saved in GCS)")
                        except Exception:
                            pass

    # Final save
    if is_master:
        xm.save({
            "step": tc.max_steps,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "loss_fn": loss_fn.state_dict(),
            "config": config_path,
            "world_size": world_size,
        }, str(out_dir / "final.pt"))
        log(f"Training complete. Final model saved to {out_dir}/final.pt")
        if gcs_path:
            gcs_dir = gcs_path.rstrip("/")
            if gcs_upload(str(out_dir / "final.pt"), f"{gcs_dir}/final.pt"):
                log(f"GCS: uploaded final.pt")

    # XLA metrics
    if is_master:
        log("\n" + "=" * 60)
        log("XLA Metrics Summary:")
        log(met.short_metrics_report())


def _mp_fn(index, config_path, resume_from, gcs_path):
    """Entry point for xmp.spawn — each process calls train_fn."""
    train_fn(index, config_path, resume_from, gcs_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LOLM on TPU Pod")
    parser.add_argument("--config", type=str, required=True,
                        help="Path to YAML config (e.g., configs/scale/7b_lolm_pod.yaml)")
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to checkpoint to resume from")
    parser.add_argument("--gcs-path", type=str, default=None,
                        help="GCS directory for checkpoint backup + auto-resume (e.g. gs://lolm-tpu-runs/lolm-7b/)")
    parser.add_argument("--no-auto-resume", action="store_true",
                        help="Skip GCS auto-resume even if --gcs-path is set")
    parser.add_argument("--use-spawn", action="store_true",
                        help="Use xmp.spawn (for single-host). Pod workers don't need this.")
    args = parser.parse_args()

    # Pre-download HF parquet files to local disk BEFORE xmp.spawn.
    # Network works fine in the main process but fails with EBADF inside
    # spawned processes (HF CDN drops concurrent connections from same IP).
    # Local parquet files are read with pyarrow — no HTTP, no EBADF.
    cfg_pre = load_config(args.config)
    # Apply env var dataset override for pre-download too
    _env_ds = os.environ.get("LOLM_DATASET", "")
    if _env_ds:
        cfg_pre.data.dataset = _env_ds
        cfg_pre.data.streaming = not _env_ds.startswith("/")
    if getattr(cfg_pre.data, 'streaming', False) and not str(cfg_pre.data.dataset).startswith('/'):
        _hf_dataset = str(cfg_pre.data.dataset)
        _hf_config  = getattr(cfg_pre.data, 'dataset_config', None) or None
        _local_dir  = '/tmp/hf_parquet_local'
        os.makedirs(_local_dir, exist_ok=True)

        # Filter out truncated files (from disk-full errors)
        _existing = sorted([f for f in os.listdir(_local_dir) if f.endswith('.parquet') and os.path.getsize(os.path.join(_local_dir, f)) > 1_000_000])
        if len(_existing) >= 4:
            print(f"Pre-download: found {len(_existing)} cached parquet files in {_local_dir}", flush=True)
        else:
            print(f"Pre-download: fetching parquet URLs for {_hf_dataset} ({_hf_config or 'default'})...", flush=True)
            try:
                import subprocess as _sp
                from huggingface_hub import list_repo_tree as _lrt
                _repo_prefix = f"sample/{_hf_config.replace('sample-', '')}" if _hf_config and 'sample' in _hf_config else "data"
                _all_files = [f.path for f in _lrt(_hf_dataset, path_in_repo=_repo_prefix, repo_type="dataset", recursive=True) if f.path.endswith('.parquet')]
                _all_files = sorted(_all_files)[:16]  # first 16 parquet files (~35GB)
                _base_url = f"https://huggingface.co/datasets/{_hf_dataset}/resolve/main"
                for _fpath in _all_files:
                    _local_name = _fpath.replace('/', '_')
                    _local_p = os.path.join(_local_dir, _local_name)
                    if not os.path.exists(_local_p) or os.path.getsize(_local_p) < 10000:
                        print(f"  wget {_fpath.split('/')[-1]}...", flush=True)
                        _sp.run(['wget', '-q', '-O', _local_p, f'{_base_url}/{_fpath}'], timeout=600, check=False)
                _existing = sorted([f for f in os.listdir(_local_dir) if f.endswith('.parquet')])
                print(f"Pre-download: {len(_existing)} files ready", flush=True)
            except Exception as _pe:
                print(f"Pre-download failed ({_pe}), falling back to streaming", flush=True)

        if len(_existing) >= 4:
            # Override config to use local files — write a small override YAML
            import yaml as _yaml
            _override_cfg = args.config + '.local_override.yaml'
            with open(_override_cfg, 'w') as _f:
                _yaml.dump({'_base_': os.path.abspath(args.config),
                            'data': {'streaming': True,
                                     'dataset': _local_dir + '/*.parquet',
                                     'tokenizer': cfg_pre.data.tokenizer}}, _f)
            args.config = _override_cfg
            print(f"Using local parquet files: {_local_dir}/*.parquet", flush=True)

    # GCS auto-resume: runs BEFORE xmp.spawn so all chips on this host share
    # the same local checkpoint path. Each host downloads independently.
    if args.gcs_path and not args.resume and not args.no_auto_resume:
        latest = gcs_find_latest(args.gcs_path)
        if latest:
            local_ckpt = "/tmp/resume_ckpt.pt"
            print(f"GCS auto-resume: found {latest}, downloading to {local_ckpt}...", flush=True)
            if gcs_download(latest, local_ckpt):
                args.resume = local_ckpt
                print(f"GCS auto-resume: will resume from step in {latest}", flush=True)
            else:
                print("GCS auto-resume: download failed, starting from scratch", flush=True)

    # Always use xmp.spawn: spawns one process per local chip.
    # In pod mode (--worker=all), PJRT auto-discovers all workers and
    # coordinates across hosts. nprocs=None = auto-detect local chip count.
    nprocs = None  # PJRT fills in local_device_count() automatically
    if args.use_spawn:
        # Explicit spawn requested (backward compat)
        nprocs = xr.local_device_count() if xr is not None else None
    xmp.spawn(
        _mp_fn,
        args=(args.config, args.resume, args.gcs_path),
        nprocs=nprocs,
    )
