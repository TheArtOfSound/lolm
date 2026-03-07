# Copyright 2026 Bryan Leonard
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

"""Training loop for LOLM."""

import argparse
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


def train(config_path: str, resume_from: str = None):
    cfg = load_config(config_path)
    tc = cfg.training

    device = torch.device(tc.device)
    print(f"Device: {device}")
    print(f"Config: {config_path}")

    # Model
    model = LOLM(cfg.model).to(device)
    params = model.count_parameters()
    print("Parameters:")
    for k, v in params.items():
        print(f"  {k}: {v:,}")

    # Loss
    loss_fn = LOLMLoss(
        lambda_future=cfg.loss.lambda_future,
        lambda_regime=cfg.loss.lambda_regime,
        lambda_mem=cfg.loss.lambda_mem,
        lambda_manifest=cfg.loss.lambda_manifest,
        future_window=cfg.loss.future_window,
    ).to(device)

    # Optimizer
    optimizer = torch.optim.AdamW(
        list(model.parameters()) + list(loss_fn.parameters()),
        lr=tc.lr,
        weight_decay=tc.weight_decay,
        betas=(tc.beta1, tc.beta2),
    )

    # Data
    print("Loading data...")
    train_loader = get_dataloader(
        cfg.data.dataset, cfg.data.cache_dir, tc.seq_len, tc.batch_size
    )

    # Output directory
    config_name = Path(config_path).stem
    out_dir = Path("runs") / config_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resume
    start_step = 0
    if resume_from:
        ckpt = torch.load(resume_from, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_step = ckpt["step"]
        if "loss_fn" in ckpt:
            loss_fn.load_state_dict(ckpt["loss_fn"])
        print(f"Resumed from step {start_step}")

    # Training loop
    model.train()
    data_iter = iter(train_loader)
    log_losses = {}
    t0 = time.time()

    for step in range(start_step, tc.max_steps):
        # Get batch
        try:
            x, y = next(data_iter)
        except StopIteration:
            data_iter = iter(train_loader)
            x, y = next(data_iter)

        x, y = x.to(device), y.to(device)

        # Learning rate schedule
        lr = get_lr(step, tc.warmup_steps, tc.max_steps, tc.lr)
        for pg in optimizer.param_groups:
            pg["lr"] = lr

        # Regime temperature
        temp = get_regime_temperature(step, cfg)

        # Forward
        out = model(x, regime_temperature=temp)

        # Loss
        total_loss, components = loss_fn(
            logits=out.logits, targets=y,
            z=out.z, h=out.h,
            regime_probs=out.regime_probs,
            regime_indices=out.regime_indices,
            mem_read=out.mem_read,
            gate_values=out.gate_values,
        )

        # NaN check — skip bad batches
        if torch.isnan(total_loss) or torch.isinf(total_loss):
            print(f"step {step+1}: NaN/Inf loss detected, skipping batch")
            optimizer.zero_grad()
            continue

        # Backward
        optimizer.zero_grad()
        total_loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), tc.grad_clip)

        # Skip if gradients exploded
        if torch.isnan(grad_norm) or grad_norm > 100 * tc.grad_clip:
            print(f"step {step+1}: grad norm {grad_norm:.1f}, skipping")
            optimizer.zero_grad()
            continue

        optimizer.step()

        # Accumulate logs
        for k, v in components.items():
            log_losses[k] = log_losses.get(k, 0.0) + v

        # MPS cache clear
        if device.type == "mps" and (step + 1) % tc.cache_clear_interval == 0:
            torch.mps.empty_cache()

        # Log
        if (step + 1) % tc.log_interval == 0:
            dt = time.time() - t0
            avg = {k: v / tc.log_interval for k, v in log_losses.items()}
            ppl = math.exp(min(avg["loss_tok"], 20))
            gate_msg = ""
            if out.gate_values is not None:
                gate_msg = f" | gate={out.gate_values.mean().item():.3f}"
            regime_msg = ""
            if out.regime_indices is not None:
                n_unique = out.regime_indices.unique().numel()
                regime_msg = f" | regimes={n_unique}"

            print(
                f"step {step+1:>6d} | loss {avg['loss_total']:.4f} | "
                f"tok {avg['loss_tok']:.4f} | ppl {ppl:.1f} | "
                f"fut {avg['loss_future']:.4f} | lr {lr:.2e} | "
                f"{tc.log_interval/dt:.1f} steps/s"
                f"{gate_msg}{regime_msg}"
            )
            log_losses = {}
            t0 = time.time()

            # Save log
            with open(out_dir / "log.jsonl", "a") as f:
                f.write(json.dumps({"step": step + 1, **avg, "lr": lr, "temp": temp}) + "\n")

        # Save checkpoint
        if (step + 1) % tc.save_interval == 0:
            ckpt_path = out_dir / f"ckpt_{step+1}.pt"
            torch.save({
                "step": step + 1,
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "loss_fn": loss_fn.state_dict(),
                "config": config_path,
            }, ckpt_path)
            print(f"Saved checkpoint: {ckpt_path}")

    # Final save
    torch.save({
        "step": tc.max_steps,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "loss_fn": loss_fn.state_dict(),
        "config": config_path,
    }, out_dir / "final.pt")
    print(f"Training complete. Final model saved to {out_dir}/final.pt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LOLM")
    parser.add_argument("--config", type=str, default="configs/base.yaml")
    parser.add_argument("--resume", type=str, default=None)
    args = parser.parse_args()
    train(args.config, args.resume)
