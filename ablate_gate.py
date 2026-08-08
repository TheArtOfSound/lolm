# Copyright 2026 Bryan Leonard & Brandyn Leonard
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Gate ablation: prove whether the latent path contributes to PPL.

Loads a checkpoint and evaluates 3 conditions on identical data:
  1. Normal gate (learned ~0.70 surface / ~0.30 latent)
  2. Surface only (gate forced to 1.0)
  3. Latent only (gate forced to 0.0)

If surface-only PPL is worse than normal, the latent path earns its keep.
"""

from __future__ import annotations

import argparse
import math
import time

import torch
import torch.nn.functional as F

from lolm.config import load_config
from lolm.model import LOLM
from lolm.data_streaming import get_streaming_dataloader


def make_fixed_gate(value: float):
    """Create a gate forward function that returns a fixed value."""
    def fixed_gate(z, h, m, r_embed):
        return torch.full_like(z, value)
    return fixed_gate


@torch.no_grad()
def eval_condition(model, batches, device, gate_override=None, use_amp=True):
    """Evaluate PPL on cached batches with optional gate override.

    Args:
        model: LOLM model in eval mode
        batches: list of (x, y) tensors already on device
        device: torch device
        gate_override: None for normal, float for forced gate value
        use_amp: whether to use bfloat16 autocast

    Returns:
        (avg_loss, ppl, gate_mean, gate_std)
    """
    model.eval()

    # Monkey-patch gate if override requested
    original_forward = None
    if gate_override is not None and model.gate is not None:
        original_forward = model.gate.forward
        model.gate.forward = make_fixed_gate(gate_override)

    total_loss = 0.0
    total_tokens = 0
    gate_vals = []

    for i, (x, y) in enumerate(batches):
        with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
            out = model(x)
            loss = F.cross_entropy(
                out.logits.view(-1, out.logits.size(-1)),
                y.view(-1),
                reduction="sum",
            )

        total_loss += loss.float().item()
        total_tokens += y.numel()

        if out.gate_values is not None:
            gate_vals.append(out.gate_values.float().mean().item())

        if (i + 1) % 10 == 0:
            running = total_loss / total_tokens
            print(f"    batch {i+1}/{len(batches)}, running loss: {running:.4f}")

    # Restore original gate
    if original_forward is not None:
        model.gate.forward = original_forward

    avg_loss = total_loss / total_tokens
    ppl = math.exp(min(avg_loss, 20))
    gate_mean = sum(gate_vals) / len(gate_vals) if gate_vals else 0.0
    gate_std = (
        (sum((g - gate_mean) ** 2 for g in gate_vals) / len(gate_vals)) ** 0.5
        if len(gate_vals) > 1 else 0.0
    )

    return avg_loss, ppl, gate_mean, gate_std


def main():
    parser = argparse.ArgumentParser(description="LOLM Gate Ablation")
    parser.add_argument("--checkpoint", type=str, required=True,
                        help="Path to checkpoint .pt file")
    parser.add_argument("--max_batches", type=int, default=50,
                        help="Number of batches to evaluate (50 = ~1.6M tokens)")
    parser.add_argument("--no_amp", action="store_true",
                        help="Disable bfloat16 autocast")
    args = parser.parse_args()

    # Load checkpoint
    print(f"Loading checkpoint: {args.checkpoint}")
    t0 = time.time()
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    cfg = load_config(ckpt["config"])
    device = torch.device(cfg.training.device)

    model = LOLM(cfg.model).to(device)
    model.load_state_dict(ckpt["model"])
    step = ckpt["step"]
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Loaded step {step} — {n_params:,} params ({time.time()-t0:.1f}s)")

    # Cache evaluation data (same batches for all conditions)
    print(f"\nCaching {args.max_batches} batches from FineWeb-Edu...")
    dataloader = get_streaming_dataloader(
        dataset_name=cfg.data.dataset,
        seq_len=cfg.training.seq_len,
        batch_size=cfg.training.batch_size,
        num_workers=2,
    )

    batches = []
    for i, (x, y) in enumerate(dataloader):
        if i >= args.max_batches:
            break
        batches.append((x.to(device), y.to(device)))
    total_tokens = sum(y.numel() for _, y in batches)
    print(f"Cached {len(batches)} batches, {total_tokens:,} tokens")

    # Run ablation
    use_amp = not args.no_amp
    print(f"\n{'='*60}")
    print(f"  GATE ABLATION — Step {step}")
    print(f"  {n_params:,} params | {len(batches)} batches | {total_tokens:,} tokens")
    print(f"{'='*60}")

    # 1. Normal gate
    print(f"\n[1/3] NORMAL GATE (learned)")
    loss_n, ppl_n, gate_mean, gate_std = eval_condition(
        model, batches, device, gate_override=None, use_amp=use_amp
    )
    print(f"  → Loss: {loss_n:.4f}  PPL: {ppl_n:.2f}  Gate: {gate_mean:.3f} ± {gate_std:.3f}")

    # 2. Surface only
    print(f"\n[2/3] SURFACE ONLY (gate=1.0, no latent contribution)")
    loss_s, ppl_s, _, _ = eval_condition(
        model, batches, device, gate_override=1.0, use_amp=use_amp
    )
    print(f"  → Loss: {loss_s:.4f}  PPL: {ppl_s:.2f}")

    # 3. Latent only
    print(f"\n[3/3] LATENT ONLY (gate=0.0, no surface contribution)")
    loss_l, ppl_l, _, _ = eval_condition(
        model, batches, device, gate_override=0.0, use_amp=use_amp
    )
    print(f"  → Loss: {loss_l:.4f}  PPL: {ppl_l:.2f}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS — Step {step}")
    print(f"{'='*60}")
    print(f"  Normal  (g≈{gate_mean:.2f}):  loss={loss_n:.4f}  PPL={ppl_n:.2f}")
    print(f"  Surface (g=1.00):  loss={loss_s:.4f}  PPL={ppl_s:.2f}")
    print(f"  Latent  (g=0.00):  loss={loss_l:.4f}  PPL={ppl_l:.2f}")
    print()

    delta_s = loss_s - loss_n
    delta_l = loss_l - loss_n
    print(f"  Removing latent (surface-only): {delta_s:+.4f} loss ({ppl_s - ppl_n:+.2f} PPL)")
    print(f"  Removing surface (latent-only): {delta_l:+.4f} loss ({ppl_l - ppl_n:+.2f} PPL)")
    print()

    if ppl_s > ppl_n * 1.005:
        pct = (ppl_s / ppl_n - 1) * 100
        print(f"  ✓ LATENT PATH CONTRIBUTES: removing it worsens PPL by {pct:.1f}%")
    elif ppl_s < ppl_n * 0.995:
        pct = (1 - ppl_s / ppl_n) * 100
        print(f"  ✗ LATENT PATH HURTS: surface-only is {pct:.1f}% better")
    else:
        print(f"  ~ INCONCLUSIVE: <0.5% difference, latent path may be negligible")

    if ppl_l > ppl_n * 1.005:
        pct = (ppl_l / ppl_n - 1) * 100
        print(f"  ✓ SURFACE PATH CONTRIBUTES: removing it worsens PPL by {pct:.1f}%")

    # Both paths needed?
    if ppl_s > ppl_n * 1.005 and ppl_l > ppl_n * 1.005:
        print(f"\n  ★ BOTH PATHS NEEDED — the blend outperforms either branch alone.")
        print(f"    This is evidence for LOLM's hybrid architecture earning its keep.")


if __name__ == "__main__":
    main()
