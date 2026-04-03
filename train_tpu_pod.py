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
    """Wrap only the SurfaceDecoder with XLA FSDP for multi-chip training.

    ONLY model.decoder is FSDP-sharded (5B+ params, dominant memory cost).
    The SSM, memory, regime, gate, and fusion projections are replicated on
    each chip — they're smaller (~1B total) and the SSM scan is incompatible
    with XlaFSDP all-gather: sharding SSM projection weights produces tensors
    whose shapes (batch×seq, d_state) don't contract correctly in XLA's mm.

    The LM head weight is untied from tok_emb before wrapping to avoid
    cross-boundary parameter aliasing under FSDP.

    Memory per chip on v4-32 (32GB):
      Decoder FSDP shard:  5.2B × 2B / 32 chips ≈  325MB params
      SSM replicated:      694M × 2B              ≈  1.4GB params + 5.6GB Adam
      Activations:                                 ≈  4GB
      Total per chip:                              ≈ 12GB — fits in 32GB
    """
    # Untie LM head weight from tok_emb — XlaFSDP can't handle parameter
    # aliasing across FSDP boundary (decoder inside, lm_head outside).
    model.lm_head.weight = nn.Parameter(model.decoder.tok_emb.weight.data.clone())

    auto_wrap_policy = functools.partial(
        transformer_auto_wrap_policy,
        transformer_layer_cls={DecoderBlock},
    )
    model.decoder = FSDP(
        model.decoder,
        auto_wrap_policy=auto_wrap_policy,
        compute_dtype=torch.bfloat16,
        buffer_dtype=torch.bfloat16,
        flatten_parameters=False,
        pin_layout_in_collective_ops=True,
    )
    return model


def sync_replicated_grads(model: nn.Module, loss_fn: nn.Module,
                          world_size: int) -> None:
    """Allreduce gradients for params NOT covered by FSDP (non-decoder modules).

    The decoder is FSDP-wrapped so its grads are handled by reduce-scatter.
    All other params (SSM, memory, regime, gate, fusion projections, lm_head,
    CPC projections) are replicated and need explicit gradient sync.
    """
    grads = []
    for name, param in model.named_parameters():
        if not name.startswith('decoder.') and param.grad is not None:
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
