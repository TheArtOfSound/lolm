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

def wrap_with_fsdp(model: nn.Module) -> FSDP:
    """Wrap LOLM model with XLA FSDP for multi-chip training.

    Wrapping policy: each DecoderBlock and SelectiveSSMLayer gets its own
    FSDP unit. This means params within each block are sharded across all
    chips, and all-gathered during forward, then reduce-scattered on backward.

    The SSM sequential scan (h[t] = A*h[t-1] + Bx[t]) operates on the
    FULL batch and time dimension within each chip — only parameter weights
    are sharded. This respects the constraint that time cannot be split.
    """
    auto_wrap_policy = functools.partial(
        transformer_auto_wrap_policy,
        transformer_layer_cls={
            DecoderBlock,       # Each Transformer layer
            SelectiveSSMLayer,  # Each SSM layer
        },
    )
    wrapped = FSDP(
        model,
        auto_wrap_policy=auto_wrap_policy,
        compute_dtype=torch.bfloat16,
        buffer_dtype=torch.bfloat16,
        shard_param_on_dim_0=True,
        pin_layout_in_collective_ops=True,
    )
    return wrapped


# ---------------------------------------------------------------------------
# Main training function — runs on every chip
# ---------------------------------------------------------------------------

def train_fn(index, config_path: str, resume_from: str = None):
    """Training function executed on each TPU chip in the pod."""

    # --- Distributed setup ---
    device = xm.xla_device()
    ordinal = xm.get_ordinal()
    world_size = xm.xrt_world_size()
    is_master = xm.is_master_ordinal()

    def log(msg):
        if is_master:
            print(msg, flush=True)

    log(f"LOLM Pod Training — {world_size} chips")
    log(f"XLA device: {device}")

    # --- Config ---
    cfg = load_config(config_path)
    tc = cfg.training

    accum_steps = tc.grad_accumulation_steps
    effective_batch = tc.batch_size * accum_steps * world_size
    log(f"Config: {config_path}")
    log(f"Batch: {tc.batch_size} x {accum_steps} accum x {world_size} chips = {effective_batch} effective")

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

    # XlaFSDP cannot shard 0-dim scalar parameters — reshape them to (1,)
    for name, param in model.named_parameters():
        if param.dim() == 0:
            param.data = param.data.unsqueeze(0)

    # XLA device: disable torch.utils.checkpoint (not XLA-compatible in 2.4)
    # The decoder/SSM check _xla_device to skip torch.utils.checkpoint
    model.decoder._xla_device = True
    if hasattr(model, "ssm") and model.ssm is not None:
        model.ssm._xla_device = True

    if use_fsdp:
        log(f"Model has {total_params/1e9:.1f}B params — using FSDP")
        # Wrap with FSDP *before* moving to device — FSDP shards the model
        # across chips; moving the full model to device first causes OOM.
        try:
            model = wrap_with_fsdp(model)
            model = model.to(device)
            log("FSDP wrapping complete")
        except RuntimeError as e:
            if "RESOURCE_EXHAUSTED" in str(e):
                log(f"FSDP OOM — falling back to single-device mode")
                del model
                import gc; gc.collect()
                model = LOLM(cfg.model).to(device)
                model.decoder._xla_device = True
                if hasattr(model, "ssm") and model.ssm is not None:
                    model.ssm._xla_device = True
            else:
                raise
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
    optimizer = torch.optim.AdamW(
        list(model.parameters()) + list(loss_fn.parameters()),
        lr=tc.lr,
        weight_decay=tc.weight_decay,
        betas=(tc.beta1, tc.beta2),
    )
    if ckpt_optimizer_state is not None:
        optimizer.load_state_dict(ckpt_optimizer_state)
        del ckpt_optimizer_state

    # --- Data (rank-aware sharding) ---
    log("Loading data...")
    if cfg.data.streaming:
        from lolm.data_streaming import get_streaming_dataloader
        train_loader = get_streaming_dataloader(
            cfg.data.dataset, tc.seq_len, tc.batch_size,
            tokenizer_name=cfg.data.tokenizer,
            num_workers=0,  # 0 avoids multi-connection HF rate limiting on TPU
            dataset_config=getattr(cfg.data, 'dataset_config', None) or None,
            rank=ordinal,
            world_size=world_size,
        )
        log(f"Streaming from: {cfg.data.dataset} (shard {ordinal}/{world_size})")
    else:
        from lolm.data import get_dataloader
        train_loader = get_dataloader(
            cfg.data.dataset, cfg.data.cache_dir, tc.seq_len, tc.batch_size
        )

    # Wrap with MpDeviceLoader — handles mark_step after each batch
    mp_loader = pl.MpDeviceLoader(train_loader, device)

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
        # LR schedule
        lr = get_lr(step, tc.warmup_steps, tc.max_steps, tc.lr)
        for pg in optimizer.param_groups:
            pg["lr"] = lr

        # Regime temperature
        temp = get_regime_temperature(step, cfg)

        # --- Gradient accumulation loop ---
        optimizer.zero_grad()
        accum_loss_total = 0.0
        accum_components = {}
        step_had_nan = False

        for micro_step in range(accum_steps):
            # Get batch (MpDeviceLoader already puts data on device)
            try:
                x, y = next(data_iter)
            except StopIteration:
                data_iter = iter(mp_loader)
                x, y = next(data_iter)

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
                scaled_loss = total_loss / accum_steps

            # NaN check — materialize loss value
            xm.mark_step()
            loss_val = total_loss.item()
            if math.isnan(loss_val) or math.isinf(loss_val) or loss_val > 1000.0:
                log(f"step {step+1}: bad loss ({loss_val:.1f}), skipping")
                step_had_nan = True
                break

            # Backward
            scaled_loss.backward()

            accum_loss_total += loss_val
            for k, v in components.items():
                accum_components[k] = accum_components.get(k, 0.0) + v / accum_steps

        if step_had_nan:
            optimizer.zero_grad()
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

        # Gradient clipping (FSDP handles gathering grads automatically)
        torch.nn.utils.clip_grad_norm_(
            list(model.parameters()), tc.grad_clip
        )
        cpc_params = list(loss_fn.parameters())
        if cpc_params:
            torch.nn.utils.clip_grad_norm_(cpc_params, tc.grad_clip)

        # XLA optimizer step
        xm.optimizer_step(optimizer)

        # Accumulate logs
        for k, v in accum_components.items():
            log_losses[k] = log_losses.get(k, 0.0) + v

        # --- Logging (master only) ---
        if (step + 1) % tc.log_interval == 0:
            dt = time.time() - t0
            avg = {k: v / tc.log_interval for k, v in log_losses.items()}
            ppl = math.exp(min(avg.get("loss_tok", 20), 20))
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

            log(
                f"step {step+1:>6d} | loss {avg.get('loss_total', 0):.4f} | "
                f"tok {avg.get('loss_tok', 0):.4f} | ppl {ppl:.1f} | "
                f"fut {avg.get('loss_future', 0):.4f} | lr {lr:.2e} | "
                f"{tc.log_interval/dt:.1f} steps/s | "
                f"{total_tokens/1e9:.2f}B tok"
                f"{gate_msg}{regime_msg}{extra_losses}"
            )
            log_losses = {}
            t0 = time.time()

            # Save log (master only)
            if is_master:
                log_entry = {"step": step + 1, **avg, "lr": lr, "temp": temp,
                             "world_size": world_size, "tokens": total_tokens}
                if out.gate_values is not None:
                    log_entry["gate_mean"] = out.gate_values.mean().item()
                if out.regime_indices is not None:
                    log_entry["regime_unique"] = out.regime_indices.unique().numel()
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
            ckpt_path = out_dir / f"ckpt_{step+1}.pt"
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
            # Barrier: all chips wait for master to finish saving
            xm.rendezvous("checkpoint")

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

    # XLA metrics
    if is_master:
        log("\n" + "=" * 60)
        log("XLA Metrics Summary:")
        log(met.short_metrics_report())


def _mp_fn(index, config_path, resume_from):
    """Entry point for xmp.spawn — each process calls train_fn."""
    train_fn(index, config_path, resume_from)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LOLM on TPU Pod")
    parser.add_argument("--config", type=str, required=True,
                        help="Path to YAML config (e.g., configs/scale/7b_lolm_pod.yaml)")
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to checkpoint to resume from")
    parser.add_argument("--use-spawn", action="store_true",
                        help="Use xmp.spawn (for single-host). Pod workers don't need this.")
    args = parser.parse_args()

    if args.use_spawn:
        # Single-host multi-chip: spawn one process per local chip
        nprocs = xr.local_device_count() if xr is not None else xm.xrt_world_size()
        xmp.spawn(
            _mp_fn,
            args=(args.config, args.resume),
            nprocs=nprocs,
        )
    else:
        # Pod mode: each worker IS a process, launched by --worker=all.
        # PJRT handles multi-host coordination automatically.
        train_fn(0, args.config, args.resume)
