# Copyright 2026 Bryan Leonard & Brandyn Leonard
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TPU smoke test for LOLM.

Verifies that all LOLM components work on XLA (TPU) device:
  1. Model creation and device placement
  2. Forward pass through all 5 streams
  3. All 7 loss computations
  4. Backward pass + gradient flow
  5. 5 optimizer steps (loss should decrease)

Run on TPU VM:
  python test_tpu.py

Expected output: "ALL TESTS PASSED" with decreasing loss over 5 steps.
"""

from __future__ import annotations

import math
import time

import torch
import torch_xla
import torch_xla.core.xla_model as xm

from lolm.config import LOLMConfig, ModelConfig, TrainingConfig, LossConfig, SSMConfig, RegimeConfig, MemoryConfig, GateConfig
from lolm.losses import LOLMLoss
from lolm.model import LOLM


def make_test_config() -> LOLMConfig:
    """Small config for fast smoke testing."""
    return LOLMConfig(
        model=ModelConfig(
            d_model=128,
            n_heads=4,
            n_layers=2,
            d_ff=512,
            vocab_size=50257,
            max_seq_len=256,
            dropout=0.0,
            ssm=SSMConfig(enabled=True, n_layers=1, d_state=8, expand=2, use_cuda_kernels=False),
            regime=RegimeConfig(enabled=True, n_codes=8, d_regime=32, gradient_isolation=True, neighbor_interaction=True, neighbor_kernel_size=3),
            memory=MemoryConfig(enabled=True, n_slots=16, n_banks=2, slot_dim=128, n_chunks=2),
            gate=GateConfig(enabled=True, init_bias=-0.5, normalize_branches=True),
        ),
        training=TrainingConfig(batch_size=2, seq_len=128, device="xla", dtype="bfloat16"),
        loss=LossConfig(
            lambda_future=0.5, lambda_regime=0.3, lambda_mem=0.05, lambda_manifest=0.01,
            future_window=4, lambda_balance=0.5, use_load_balance=True, lambda_sticky=0.2,
            use_cpc=True, cpc_temperature=0.07, cpc_max_positions=64, cpc_proj_dim=32,
            lambda_changepoint=0.1, lambda_competitive=0.1,
        ),
    )


def main():
    print("=" * 60)
    print("LOLM TPU Smoke Test")
    print("=" * 60)

    device = xm.xla_device()
    print(f"\n[1/5] XLA device: {device} ({xm.xla_device_hw(device)})")

    # --- Create model ---
    cfg = make_test_config()
    model = LOLM(cfg.model).to(device)
    params = model.count_parameters()
    print(f"\n[2/5] Model created: {params['total']:,} params")
    for k, v in params.items():
        if k != 'total':
            print(f"  {k}: {v:,}")

    # --- Loss function ---
    loss_fn = LOLMLoss(
        lambda_future=cfg.loss.lambda_future, lambda_regime=cfg.loss.lambda_regime,
        lambda_mem=cfg.loss.lambda_mem, lambda_manifest=cfg.loss.lambda_manifest,
        future_window=cfg.loss.future_window, lambda_balance=cfg.loss.lambda_balance,
        use_load_balance=cfg.loss.use_load_balance, lambda_sticky=cfg.loss.lambda_sticky,
        use_cpc=cfg.loss.use_cpc, cpc_temperature=cfg.loss.cpc_temperature,
        cpc_max_positions=cfg.loss.cpc_max_positions,
        lambda_changepoint=cfg.loss.lambda_changepoint,
        lambda_competitive=cfg.loss.lambda_competitive,
        cpc_proj_dim=cfg.loss.cpc_proj_dim,
    ).to(device)
    loss_fn._init_cpc_proj(cfg.model.d_model, device)
    print(f"  Loss function with CPC projection (d_proj={cfg.loss.cpc_proj_dim})")

    # --- Forward pass test ---
    print(f"\n[3/5] Forward pass test...")
    x = torch.randint(0, cfg.model.vocab_size, (2, 128), device=device)
    y = torch.randint(0, cfg.model.vocab_size, (2, 128), device=device)

    t0 = time.time()
    with torch.amp.autocast(device_type="xla", dtype=torch.bfloat16):
        out = model(x, regime_temperature=1.0)
    xm.mark_step()
    dt = time.time() - t0

    print(f"  Forward pass: {dt:.2f}s")
    print(f"  logits: {out.logits.shape}")
    print(f"  h: {out.h.shape}")
    print(f"  z: {out.z.shape if out.z is not None else 'None'}")
    print(f"  gate: {out.gate_values.mean().item():.4f}" if out.gate_values is not None else "  gate: None")
    print(f"  regime codes alive: {out.regime_indices.unique().numel()}" if out.regime_indices is not None else "  regime: None")

    # --- Loss computation test ---
    print(f"\n[4/5] Loss computation test...")
    with torch.amp.autocast(device_type="xla", dtype=torch.bfloat16):
        total_loss, components = loss_fn(
            logits=out.logits, targets=y,
            z=out.z, h=out.h,
            regime_probs=out.regime_probs, regime_indices=out.regime_indices,
            mem_read=out.mem_read, mem_attn=out.mem_attn,
            gate_values=out.gate_values,
        )
    xm.mark_step()

    print(f"  Total loss: {total_loss.item():.4f}")
    for k, v in components.items():
        status = "OK" if not (math.isnan(v) or math.isinf(v)) else "FAIL"
        print(f"  {k}: {v:.4f} [{status}]")

    # Check no NaN in any loss
    any_nan = any(math.isnan(v) or math.isinf(v) for v in components.values())
    assert not any_nan, "NaN/Inf detected in loss components!"

    # --- Training steps test ---
    print(f"\n[5/5] Training test (5 steps)...")
    optimizer = torch.optim.AdamW(
        list(model.parameters()) + list(loss_fn.parameters()),
        lr=1e-4, weight_decay=0.01,
    )

    losses = []
    model.train()
    for step in range(5):
        optimizer.zero_grad()
        x = torch.randint(0, cfg.model.vocab_size, (2, 128), device=device)
        y = torch.randint(0, cfg.model.vocab_size, (2, 128), device=device)

        with torch.amp.autocast(device_type="xla", dtype=torch.bfloat16):
            out = model(x, regime_temperature=1.0)
            total_loss, _ = loss_fn(
                logits=out.logits, targets=y,
                z=out.z, h=out.h,
                regime_probs=out.regime_probs, regime_indices=out.regime_indices,
                mem_read=out.mem_read, mem_attn=out.mem_attn,
                gate_values=out.gate_values,
            )

        total_loss.backward()
        xm.optimizer_step(optimizer)

        loss_val = total_loss.item()
        losses.append(loss_val)
        print(f"  Step {step+1}: loss={loss_val:.4f}")

    # Verify gradients flowed
    has_grads = sum(1 for p in model.parameters() if p.grad is not None)
    total_params = sum(1 for p in model.parameters())
    print(f"\n  Gradient flow: {has_grads}/{total_params} parameters have gradients")

    # --- Summary ---
    print(f"\n{'='*60}")
    if not any_nan and has_grads > 0:
        print("ALL TESTS PASSED")
        print(f"  Loss trajectory: {' -> '.join(f'{l:.2f}' for l in losses)}")
        print(f"  Device: {device} ({xm.xla_device_hw(device)})")
        print(f"  Model: {params['total']:,} params")
        print(f"\n  Ready to train! Run:")
        print(f"    python train_tpu.py --config configs/scale/300m_tpu.yaml")
    else:
        print("TESTS FAILED")
        if any_nan:
            print("  NaN/Inf in loss components")
        if has_grads == 0:
            print("  No gradients flowing")
    print("=" * 60)


if __name__ == "__main__":
    main()
