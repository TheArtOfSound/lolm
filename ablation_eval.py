# Copyright 2026 Bryan Leonard
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Inference-time ablation evaluation for LOLM.

Tests which architectural components actually contribute to performance
by disabling them at eval time using forward hooks (no retraining needed).

Produces a results table suitable for grant applications and papers:

    | Variant          | PPL   | Delta | Component Proved |
    |------------------|-------|-------|------------------|
    | Full LOLM        | 36.2  | ---   | Baseline         |
    | No Memory        | 38.1  | +5.2% | Memory helps     |
    | No Regime        | 37.4  | +3.3% | Regimes help     |
    | No SSM (gate=1)  | 39.5  | +9.1% | SSM path helps   |
    | No Gate (g=0.5)  | 37.8  | +4.4% | Dynamic gate helps|
    | Decoder Only     | 41.2  | +13.8%| All latent helps |

Also computes positional PPL curves showing how each component
affects long-range modeling (positions 0-256 vs 768-1024).

Usage:
    python ablation_eval.py --checkpoint runs/300m_v3/ckpt_25000.pt
    python ablation_eval.py --checkpoint runs/300m_v3/ckpt_25000.pt --quick
"""

from __future__ import annotations

import argparse
import math
import sys
from contextlib import contextmanager

import tiktoken
import torch
import torch.nn.functional as F

from lolm.config import load_config
from lolm.model import LOLM


# ── Data Loading ───────────────────────────────────────────────────────────

def get_eval_batches(seq_len: int = 1024, n_batches: int = 50,
                     device: str = "cuda") -> list[torch.Tensor]:
    """Load WikiText-103 test split and chunk into evaluation batches."""
    from datasets import load_dataset

    enc = tiktoken.get_encoding("gpt2")
    ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="test")
    text = "\n\n".join([x for x in ds["text"] if x.strip()])
    tokens = enc.encode(text)

    batches = []
    stride = seq_len + 1
    for i in range(n_batches):
        start = i * stride
        if start + stride > len(tokens):
            break
        chunk = torch.tensor(
            tokens[start:start + stride], dtype=torch.long, device=device
        ).unsqueeze(0)
        batches.append(chunk)

    print(f"Loaded {len(batches)} eval batches, seq_len={seq_len}")
    return batches


# ── Ablation Hooks ─────────────────────────────────────────────────────────

@contextmanager
def ablation_hooks(model: LOLM, ablation: str):
    """Context manager that applies/removes ablation hooks cleanly.

    Ablation modes:
        none         - Full model (baseline)
        no_memory    - Zero out memory contribution
        no_regime    - Zero out regime contribution
        no_ssm       - Force gate=1.0 (surface only, SSM ignored)
        no_gate      - Force gate=0.5 (constant blend, no context-sensitivity)
        decoder_only - Disable all latent: gate=1.0 + no memory + no regime
    """
    hooks = []

    def zero_hook(module, input, output):
        return torch.zeros_like(output)

    def gate_one_hook(module, input, output):
        return torch.ones_like(output)

    def gate_half_hook(module, input, output):
        return torch.full_like(output, 0.5)

    try:
        if ablation == "none":
            pass

        elif ablation == "no_memory":
            if model.proj_m is not None:
                hooks.append(model.proj_m.register_forward_hook(zero_hook))

        elif ablation == "no_regime":
            if model.proj_r is not None:
                hooks.append(model.proj_r.register_forward_hook(zero_hook))

        elif ablation == "no_ssm":
            if model.gate is not None:
                hooks.append(model.gate.register_forward_hook(gate_one_hook))

        elif ablation == "no_gate":
            if model.gate is not None:
                hooks.append(model.gate.register_forward_hook(gate_half_hook))

        elif ablation == "decoder_only":
            if model.gate is not None:
                hooks.append(model.gate.register_forward_hook(gate_one_hook))
            if model.proj_m is not None:
                hooks.append(model.proj_m.register_forward_hook(zero_hook))
            if model.proj_r is not None:
                hooks.append(model.proj_r.register_forward_hook(zero_hook))

        else:
            raise ValueError(f"Unknown ablation: {ablation}")

        yield

    finally:
        for h in hooks:
            h.remove()


# ── Evaluation Functions ───────────────────────────────────────────────────

@torch.no_grad()
def eval_perplexity(model: LOLM, batches: list[torch.Tensor],
                    ablation: str = "none") -> tuple[float, float]:
    """Evaluate perplexity with an ablation applied.

    Returns (avg_loss, perplexity).
    """
    model.eval()
    total_loss = 0.0
    total_tokens = 0

    with ablation_hooks(model, ablation):
        for batch in batches:
            x = batch[:, :-1]
            y = batch[:, 1:]
            out = model(x)
            loss = F.cross_entropy(
                out.logits.view(-1, out.logits.size(-1)),
                y.reshape(-1),
                reduction="sum",
            )
            total_loss += loss.item()
            total_tokens += y.numel()

    avg_loss = total_loss / total_tokens
    ppl = math.exp(min(avg_loss, 20))
    return avg_loss, ppl


@torch.no_grad()
def eval_positional_ppl(model: LOLM, batches: list[torch.Tensor],
                        ablation: str = "none",
                        n_bins: int = 4) -> list[float]:
    """Compute PPL at different token positions.

    Splits each sequence into n_bins chunks and computes PPL per chunk.
    Shows whether components help more with long-range context.

    Returns list of PPL values, one per position bin.
    """
    model.eval()
    seq_len = batches[0].size(1) - 1
    bin_size = seq_len // n_bins
    bin_losses = [0.0] * n_bins
    bin_tokens = [0] * n_bins

    with ablation_hooks(model, ablation):
        for batch in batches:
            x = batch[:, :-1]
            y = batch[:, 1:]
            out = model(x)

            # Per-token losses
            logits_flat = out.logits.view(-1, out.logits.size(-1))
            targets_flat = y.reshape(-1)
            per_token_loss = F.cross_entropy(
                logits_flat, targets_flat, reduction="none"
            ).view(y.shape)  # (B, T)

            for b in range(n_bins):
                start = b * bin_size
                end = start + bin_size if b < n_bins - 1 else seq_len
                chunk_loss = per_token_loss[:, start:end].sum().item()
                chunk_tokens = (end - start) * y.size(0)
                bin_losses[b] += chunk_loss
                bin_tokens[b] += chunk_tokens

    ppls = []
    for i in range(n_bins):
        avg = bin_losses[i] / bin_tokens[i] if bin_tokens[i] > 0 else 0
        ppls.append(math.exp(min(avg, 20)))

    return ppls


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOLM Ablation Evaluation")
    parser.add_argument("--checkpoint", type=str, required=True)
    parser.add_argument("--n_batches", type=int, default=50,
                        help="Number of eval batches")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: fewer batches")
    parser.add_argument("--positional", action="store_true",
                        help="Also compute positional PPL curves")
    args = parser.parse_args()

    if args.quick:
        args.n_batches = 10

    # ── Load model ─────────────────────────────────────────────────────
    print("Loading checkpoint...")
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    cfg = load_config(ckpt["config"])
    device = torch.device(cfg.training.device)

    model = LOLM(cfg.model).to(device)
    model.load_state_dict(ckpt["model"], strict=False)
    model.eval()
    step = ckpt.get("step", "?")
    print(f"Loaded from step {step}, device={device}")

    # Print component status
    params = model.count_parameters()
    print(f"Parameters: {params['total']:,}")
    print(f"  decoder: {params.get('decoder', 0):,}")
    print(f"  ssm:     {params.get('ssm', 0):,}")
    print(f"  memory:  {params.get('memory', 0):,}")
    print(f"  regime:  {params.get('regime', 0):,}")
    print(f"  gate:    {params.get('gate', 0):,}")

    # ── Load eval data ─────────────────────────────────────────────────
    batches = get_eval_batches(
        seq_len=cfg.training.seq_len,
        n_batches=args.n_batches,
        device=str(device),
    )

    # ── Run ablations ──────────────────────────────────────────────────
    ablations = [
        ("Full LOLM",        "none"),
        ("No Memory",        "no_memory"),
        ("No Regime",        "no_regime"),
        ("No SSM (gate=1)",  "no_ssm"),
        ("No Gate (g=0.5)",  "no_gate"),
        ("Decoder Only",     "decoder_only"),
    ]

    results = {}
    print("\n" + "=" * 70)
    print("ABLATION STUDY")
    print("=" * 70)

    for label, mode in ablations:
        print(f"\nEvaluating: {label} ({mode})...", end=" ", flush=True)
        avg_loss, ppl = eval_perplexity(model, batches, ablation=mode)
        results[mode] = {"label": label, "loss": avg_loss, "ppl": ppl}
        print(f"PPL = {ppl:.2f}")

    # ── Results table ──────────────────────────────────────────────────
    baseline_ppl = results["none"]["ppl"]

    print("\n" + "=" * 70)
    print(f"{'Variant':<22} {'PPL':>8} {'Delta':>10} {'Component Proved'}")
    print("-" * 70)

    for _, mode in ablations:
        r = results[mode]
        if mode == "none":
            delta_str = "---"
        else:
            delta_pct = (r["ppl"] - baseline_ppl) / baseline_ppl * 100
            delta_str = f"+{delta_pct:.1f}%" if delta_pct > 0 else f"{delta_pct:.1f}%"

        # What this proves
        proofs = {
            "none": "Baseline",
            "no_memory": "Memory helps" if r["ppl"] > baseline_ppl else "Memory NOT helping",
            "no_regime": "Regimes help" if r["ppl"] > baseline_ppl else "Regimes NOT helping",
            "no_ssm": "SSM path helps" if r["ppl"] > baseline_ppl else "SSM NOT helping",
            "no_gate": "Dynamic gate helps" if r["ppl"] > baseline_ppl else "Gate NOT helping",
            "decoder_only": "All latent helps" if r["ppl"] > baseline_ppl else "Latent NOT helping",
        }

        print(f"{r['label']:<22} {r['ppl']:>8.2f} {delta_str:>10} {proofs[mode]}")

    print("=" * 70)

    # ── Positional PPL (optional) ──────────────────────────────────────
    if args.positional:
        print("\n" + "=" * 70)
        print("POSITIONAL PPL (how components affect long-range modeling)")
        print("=" * 70)

        n_bins = 4
        seq_len = cfg.training.seq_len
        bin_size = seq_len // n_bins

        # Only run for key variants
        pos_variants = ["none", "no_memory", "no_ssm", "decoder_only"]
        pos_results = {}

        for mode in pos_variants:
            label = results[mode]["label"]
            print(f"\nPositional PPL for: {label}...", flush=True)
            ppls = eval_positional_ppl(model, batches, ablation=mode, n_bins=n_bins)
            pos_results[mode] = ppls

        # Print positional table
        headers = [f"pos {i * bin_size}-{(i + 1) * bin_size}" for i in range(n_bins)]
        print(f"\n{'Variant':<22}", end="")
        for h in headers:
            print(f" {h:>14}", end="")
        print()
        print("-" * (22 + 15 * n_bins))

        for mode in pos_variants:
            label = results[mode]["label"]
            print(f"{label:<22}", end="")
            for ppl in pos_results[mode]:
                print(f" {ppl:>14.2f}", end="")
            print()

        # Show improvement from latent at later positions
        if "none" in pos_results and "decoder_only" in pos_results:
            print(f"\n{'Latent advantage':<22}", end="")
            for i in range(n_bins):
                full = pos_results["none"][i]
                dec = pos_results["decoder_only"][i]
                pct = (dec - full) / dec * 100
                print(f" {pct:>13.1f}%", end="")
            print()

        print("=" * 70)
        print("\nIf latent advantage grows at later positions, LOLM's memory/SSM")
        print("provide measurable long-range modeling benefit over pure decoder.")


if __name__ == "__main__":
    main()
