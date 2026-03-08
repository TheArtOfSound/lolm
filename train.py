# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Training loop for LOLM.

Supports:
  - Gradient accumulation for large effective batch sizes
  - AMP (automatic mixed precision) with bfloat16 on CUDA
  - torch.compile for kernel fusion on CUDA
  - Streaming data from HuggingFace for large datasets
  - DDP (Distributed Data Parallel) for multi-GPU training

Single-GPU:
  python train.py --config configs/scale/300m_v3.yaml

Multi-GPU (auto-detected via torchrun):
  torchrun --nproc_per_node=4 train.py --config configs/scale/300m_v3_4gpu.yaml
"""

import argparse
import contextlib
import json
import math
import os
import time
from pathlib import Path

import torch
from tqdm import tqdm

from lolm.config import load_config
from lolm.data import get_dataloader
from lolm.losses import LOLMLoss
from lolm.model import LOLM


# ---------------------------------------------------------------------------
# Distributed helpers
# ---------------------------------------------------------------------------

def is_distributed():
    """Check if running under torchrun / torch.distributed.launch."""
    return "RANK" in os.environ and "WORLD_SIZE" in os.environ


def setup_distributed():
    """Initialize DDP process group. Returns (rank, local_rank, world_size)."""
    import torch.distributed as dist
    dist.init_process_group(backend="nccl")
    rank = dist.get_rank()
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    world_size = dist.get_world_size()
    torch.cuda.set_device(local_rank)
    return rank, local_rank, world_size


def cleanup_distributed():
    """Clean up DDP process group."""
    import torch.distributed as dist
    if dist.is_initialized():
        dist.destroy_process_group()


# ---------------------------------------------------------------------------
# LR + temperature schedules
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


def _raw_model(model):
    """Unwrap DDP / torch.compile to get the raw LOLM model."""
    m = model
    if hasattr(m, "module"):        # DDP wrapper
        m = m.module
    if hasattr(m, "_orig_mod"):     # torch.compile wrapper
        m = m._orig_mod
    return m


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------

def train(config_path: str, resume_from: str = None):
    cfg = load_config(config_path)
    tc = cfg.training

    # --- Distributed setup (auto-detected) ---
    distributed = is_distributed()
    if distributed:
        rank, local_rank, world_size = setup_distributed()
        device = torch.device(f"cuda:{local_rank}")
    else:
        rank, local_rank, world_size = 0, 0, 1
        device = torch.device(tc.device)

    is_main = (rank == 0)  # Only rank 0 logs and saves

    if is_main:
        print(f"Device: {device}")
        print(f"Config: {config_path}")
        if distributed:
            print(f"DDP: {world_size} GPUs, rank {rank}")

    # Determine dtype
    dtype_map = {
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }
    train_dtype = dtype_map.get(tc.dtype, torch.float32)

    # AMP setup — only for CUDA with float16/bfloat16
    use_amp = (device.type == "cuda" and train_dtype != torch.float32)
    if use_amp:
        use_scaler = (train_dtype == torch.float16)
        amp_ctx = torch.amp.autocast(device_type="cuda", dtype=train_dtype)
        scaler = torch.amp.GradScaler("cuda", enabled=use_scaler)
        if is_main:
            print(f"AMP enabled: {tc.dtype}" + (" + GradScaler" if use_scaler else ""))
    else:
        from contextlib import nullcontext
        amp_ctx = nullcontext()
        scaler = None
        if is_main:
            print(f"AMP disabled (dtype={tc.dtype}, device={device.type})")

    # Gradient accumulation
    accum_steps = tc.grad_accumulation_steps
    effective_batch = tc.batch_size * accum_steps * world_size
    if is_main:
        print(f"Batch size: {tc.batch_size} x {accum_steps} accum x {world_size} GPUs = {effective_batch} effective")

    # Model
    model = LOLM(cfg.model).to(device)
    if is_main:
        params = model.count_parameters()
        print("Parameters:")
        for k, v in params.items():
            print(f"  {k}: {v:,}")

    # Gradient checkpointing (trade ~30% compute for ~50% memory savings)
    if getattr(tc, "gradient_checkpointing", False):
        model.decoder.use_gradient_checkpoint = True
        if hasattr(model, "ssm") and model.ssm is not None:
            model.ssm.use_gradient_checkpoint = True
        if is_main:
            print("Gradient checkpointing enabled (decoder + SSM layers)")

    # Loss
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
    if cfg.loss.cpc_proj_dim > 0:
        loss_fn._init_cpc_proj(cfg.model.d_model, device)
        if is_main:
            print(f"CPC projection: d_model={cfg.model.d_model} → d_proj={cfg.loss.cpc_proj_dim}, temp={cfg.loss.cpc_temperature}")

    # Resume BEFORE torch.compile and DDP wrapping
    start_step = 0
    ckpt_optimizer_state = None
    if resume_from:
        ckpt = torch.load(resume_from, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model"])
        start_step = ckpt["step"]
        ckpt_optimizer_state = ckpt.get("optimizer")
        if "loss_fn" in ckpt:
            loss_fn.load_state_dict(ckpt["loss_fn"])
        if scaler is not None and "scaler" in ckpt:
            scaler.load_state_dict(ckpt["scaler"])
        if is_main:
            print(f"Resumed from step {start_step}")
        del ckpt

    # torch.compile AFTER resume, BEFORE DDP
    if tc.compile and device.type == "cuda":
        if is_main:
            print("Compiling model with torch.compile...")
        model = torch.compile(model)
        if is_main:
            print("Model compiled.")

    # DDP wrapping AFTER compile
    if distributed:
        from torch.nn.parallel import DistributedDataParallel as DDP
        model = DDP(model, device_ids=[local_rank])
        if is_main:
            print(f"Model wrapped in DDP (device_ids=[{local_rank}])")

    # Optimizer (fused=True on CUDA for kernel fusion speedup)
    adam_kwargs = dict(
        lr=tc.lr,
        weight_decay=tc.weight_decay,
        betas=(tc.beta1, tc.beta2),
    )
    if device.type == "cuda":
        adam_kwargs["fused"] = True
        if is_main:
            print("AdamW: using fused CUDA implementation")
    optimizer = torch.optim.AdamW(
        list(model.parameters()) + list(loss_fn.parameters()),
        **adam_kwargs,
    )
    if ckpt_optimizer_state is not None:
        optimizer.load_state_dict(ckpt_optimizer_state)
        del ckpt_optimizer_state

    # Data — each DDP rank gets a different shard of the stream
    if is_main:
        print("Loading data...")
    if cfg.data.streaming:
        from lolm.data_streaming import get_streaming_dataloader
        train_loader = get_streaming_dataloader(
            cfg.data.dataset, tc.seq_len, tc.batch_size,
            tokenizer_name=cfg.data.tokenizer,
            rank=rank, world_size=world_size,
        )
        if is_main:
            print(f"Streaming from: {cfg.data.dataset}")
    else:
        train_loader = get_dataloader(
            cfg.data.dataset, cfg.data.cache_dir, tc.seq_len, tc.batch_size
        )

    # Output directory
    config_name = Path(config_path).stem
    out_dir = Path("runs") / config_name
    if is_main:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Training loop
    model.train()
    data_iter = iter(train_loader)
    log_losses = {}
    t0 = time.time()
    consecutive_nan = 0  # Track consecutive NaN steps for recovery
    nan_lr_reductions = 0  # How many times we've halved LR due to NaN

    for step in range(start_step, tc.max_steps):
        # Learning rate schedule
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
            # DDP: skip gradient sync on non-final micro-steps (saves communication)
            is_last_micro = (micro_step == accum_steps - 1)
            sync_ctx = contextlib.nullcontext() if (is_last_micro or not distributed) else model.no_sync()

            with sync_ctx:
                # Get batch
                try:
                    x, y = next(data_iter)
                except StopIteration:
                    data_iter = iter(train_loader)
                    x, y = next(data_iter)

                x, y = x.to(device), y.to(device)

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
                    # Scale loss by accumulation steps
                    scaled_loss = total_loss / accum_steps

                # NaN/Inf/runaway check — skip BEFORE backward to prevent OOM
                if (torch.isnan(total_loss) or torch.isinf(total_loss)
                        or total_loss.item() > 100.0):
                    if is_main:
                        print(f"step {step+1}: bad loss ({total_loss.item():.1f}), skipping entire step")
                    step_had_nan = True
                    break

                # Backward (with scaler if using fp16)
                if scaler is not None:
                    scaler.scale(scaled_loss).backward()
                else:
                    scaled_loss.backward()

            accum_loss_total += total_loss.item()
            for k, v in components.items():
                accum_components[k] = accum_components.get(k, 0.0) + v / accum_steps

        # If NaN detected, zero all gradients and skip this step entirely
        if step_had_nan:
            optimizer.zero_grad()
            consecutive_nan += 1
            # NaN recovery: after 100 consecutive NaN steps, halve LR
            if consecutive_nan >= 100 and nan_lr_reductions < 3:
                nan_lr_reductions += 1
                tc.lr = tc.lr * 0.5
                if is_main:
                    print(f"  [NaN recovery] 100+ consecutive NaN steps. "
                          f"Halving LR to {tc.lr:.2e} (reduction {nan_lr_reductions}/3)")
                # Reset optimizer momentum to escape corrupted state
                for group in optimizer.param_groups:
                    for p in group['params']:
                        state = optimizer.state.get(p)
                        if state and 'exp_avg' in state:
                            state['exp_avg'].zero_()
                            state['exp_avg_sq'].zero_()
                consecutive_nan = 0  # Reset counter after intervention
            elif consecutive_nan >= 100:
                if is_main:
                    print(f"  [NaN FATAL] 3 LR reductions exhausted. Saving emergency checkpoint.")
                    raw = _raw_model(model)
                    torch.save({
                        "step": step + 1, "model": raw.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "loss_fn": loss_fn.state_dict(),
                        "config": config_path,
                    }, out_dir / f"ckpt_emergency_{step+1}.pt")
                break
            continue
        consecutive_nan = 0  # Reset on successful step

        # Gradient clipping on ALL parameters (model + loss_fn projections)
        all_params = list(model.parameters()) + list(loss_fn.parameters())
        if scaler is not None:
            scaler.unscale_(optimizer)

        grad_norm = torch.nn.utils.clip_grad_norm_(all_params, tc.grad_clip)

        # Skip only if gradients are truly catastrophic (NaN or extreme)
        if torch.isnan(grad_norm) or torch.isinf(grad_norm):
            if is_main:
                print(f"step {step+1}: grad norm {grad_norm:.1f}, skipping")
            optimizer.zero_grad()
            continue

        # Optimizer step
        if scaler is not None:
            scaler.step(optimizer)
            scaler.update()
        else:
            optimizer.step()

        # Accumulate logs (using averaged components from accumulation)
        for k, v in accum_components.items():
            log_losses[k] = log_losses.get(k, 0.0) + v

        # MPS cache clear
        if device.type == "mps" and (step + 1) % tc.cache_clear_interval == 0:
            torch.mps.empty_cache()
        if device.type == "cuda" and (step + 1) % tc.cache_clear_interval == 0:
            torch.cuda.empty_cache()

        # Log (rank 0 only)
        if is_main and (step + 1) % tc.log_interval == 0:
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

            # Build extra loss components string (only non-zero ones)
            extra_losses = ""
            for lname, lkey in [
                ("chg", "loss_changepoint"), ("comp", "loss_competitive"),
                ("reg", "loss_regime"), ("mem", "loss_mem"), ("man", "loss_manifest"),
            ]:
                val = avg.get(lkey, 0.0)
                if abs(val) > 1e-8:
                    extra_losses += f" | {lname}={val:.4f}"

            gpu_info = f" | {world_size}gpu" if distributed else ""
            print(
                f"step {step+1:>6d} | loss {avg.get('loss_total', 0):.4f} | "
                f"tok {avg.get('loss_tok', 0):.4f} | ppl {ppl:.1f} | "
                f"fut {avg.get('loss_future', 0):.4f} | lr {lr:.2e} | "
                f"{tc.log_interval/dt:.1f} steps/s"
                f"{gate_msg}{regime_msg}{extra_losses}{gpu_info}"
            )
            log_losses = {}
            t0 = time.time()

            # Save log with extra diagnostics
            log_entry = {"step": step + 1, **avg, "lr": lr, "temp": temp}
            if out.gate_values is not None:
                log_entry["gate_mean"] = out.gate_values.mean().item()
            if out.regime_indices is not None:
                log_entry["regime_unique"] = out.regime_indices.unique().numel()
            if distributed:
                log_entry["world_size"] = world_size
            with open(out_dir / "log.jsonl", "a") as f:
                f.write(json.dumps(log_entry) + "\n")

        # Gradient diagnostic (lightweight, every 2000 steps, rank 0 only)
        if is_main and (step + 1) % 2000 == 0:
            raw = _raw_model(model)
            diag = []
            # Memory grad check
            if hasattr(raw, 'memory') and raw.memory is not None:
                for bi, bank in enumerate(raw.memory.banks):
                    for pn, p in bank.named_parameters():
                        if any(k in pn for k in ["write_proj", "forget_gate", "write_gate"]):
                            g = "NONE" if p.grad is None else f"{p.grad.norm().item():.6f}"
                            diag.append(f"mem[{bi}].{pn}={g}")
            # CPC projection grad check
            if loss_fn.cpc_z_proj is not None:
                for name, proj in [("cpc_z", loss_fn.cpc_z_proj), ("cpc_h", loss_fn.cpc_h_proj)]:
                    for pn, p in proj.named_parameters():
                        if p.grad is not None:
                            diag.append(f"{name}.{pn}={p.grad.norm().item():.6f}")
                        else:
                            diag.append(f"{name}.{pn}=NONE")
            elif loss_fn.future_proj is not None:
                p = loss_fn.future_proj.weight
                g = "NONE" if p.grad is None else f"{p.grad.norm().item():.6f}"
                diag.append(f"future_proj={g}")
            print(f"  [grad check step {step+1}] " + " | ".join(diag[:8]))

            # Regime histogram
            if out.regime_indices is not None:
                hist = torch.bincount(out.regime_indices.view(-1), minlength=cfg.model.regime.n_codes)
                total = hist.sum().item()
                top5 = hist.topk(min(5, len(hist)))
                hist_str = " ".join(f"c{top5.indices[i]}:{top5.values[i].item()}/{total}" for i in range(len(top5.indices)))
                entropy = -(hist.float() / total * (hist.float() / total + 1e-10).log()).sum().item()
                max_entropy = torch.tensor(float(cfg.model.regime.n_codes)).log().item()
                print(f"  [regime hist step {step+1}] top5: {hist_str} | usage_entropy={entropy:.3f}/{max_entropy:.3f}")

        # Save checkpoint (rank 0 only, use raw model to strip DDP/compile wrappers)
        if is_main and (step + 1) % tc.save_interval == 0:
            ckpt_path = out_dir / f"ckpt_{step+1}.pt"
            raw = _raw_model(model)
            ckpt_data = {
                "step": step + 1,
                "model": raw.state_dict(),
                "optimizer": optimizer.state_dict(),
                "loss_fn": loss_fn.state_dict(),
                "config": config_path,
            }
            if scaler is not None:
                ckpt_data["scaler"] = scaler.state_dict()
            torch.save(ckpt_data, ckpt_path)
            print(f"Saved checkpoint: {ckpt_path}")

        # DDP barrier after checkpoint so all ranks wait
        if distributed and (step + 1) % tc.save_interval == 0:
            import torch.distributed as dist
            dist.barrier()

    # Final save (rank 0 only)
    if is_main:
        raw = _raw_model(model)
        final_data = {
            "step": tc.max_steps,
            "model": raw.state_dict(),
            "optimizer": optimizer.state_dict(),
            "loss_fn": loss_fn.state_dict(),
            "config": config_path,
        }
        if scaler is not None:
            final_data["scaler"] = scaler.state_dict()
        torch.save(final_data, out_dir / "final.pt")
        print(f"Training complete. Final model saved to {out_dir}/final.pt")

    # Clean up distributed
    if distributed:
        cleanup_distributed()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LOLM")
    parser.add_argument("--config", type=str, default="configs/base.yaml")
    parser.add_argument("--resume", type=str, default=None)
    args = parser.parse_args()
    train(args.config, args.resume)
