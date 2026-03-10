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

"""Evaluation: perplexity, text generation, regime/gate analysis."""

import argparse
import math

import tiktoken
import torch

from lolm.config import load_config
from lolm.data import get_dataloader
from lolm.model import LOLM


@torch.no_grad()
def compute_perplexity(model, dataloader, device, max_batches=100):
    """Compute perplexity on validation data."""
    model.eval()
    total_loss = 0.0
    total_tokens = 0
    import torch.nn.functional as F

    for i, (x, y) in enumerate(dataloader):
        if i >= max_batches:
            break
        x, y = x.to(device), y.to(device)
        out = model(x)
        loss = F.cross_entropy(
            out.logits.view(-1, out.logits.size(-1)),
            y.view(-1),
            reduction="sum",
        )
        total_loss += loss.item()
        total_tokens += y.numel()

    avg_loss = total_loss / total_tokens
    return math.exp(min(avg_loss, 20))


@torch.no_grad()
def generate(model, prompt: str, max_new_tokens: int = 200,
             temperature: float = 0.8, top_k: int = 50,
             device: str = "mps"):
    """Generate text from a prompt."""
    model.eval()
    enc = tiktoken.get_encoding("gpt2")
    token_ids = enc.encode(prompt)
    x = torch.tensor([token_ids], dtype=torch.long, device=device)

    for _ in range(max_new_tokens):
        # Crop to max_seq_len
        x_cond = x[:, -model.cfg.max_seq_len:]
        out = model(x_cond)
        logits = out.logits[:, -1, :] / temperature

        # Top-k filtering
        if top_k > 0:
            v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
            logits[logits < v[:, [-1]]] = float("-inf")

        probs = torch.softmax(logits, dim=-1)
        next_id = torch.multinomial(probs, num_samples=1)
        x = torch.cat([x, next_id], dim=1)

        # Stop at end-of-text
        if next_id.item() == enc.eot_token:
            break

    return enc.decode(x[0].tolist())


@torch.no_grad()
def analyze_gate(model, dataloader, device, max_batches=10):
    """Analyze manifestation gate statistics."""
    model.eval()
    gate_means = []
    gate_stds = []

    for i, (x, _) in enumerate(dataloader):
        if i >= max_batches:
            break
        x = x.to(device)
        out = model(x)
        if out.gate_values is not None:
            gate_means.append(out.gate_values.mean().item())
            gate_stds.append(out.gate_values.std().item())

    if gate_means:
        print(f"Gate mean: {sum(gate_means)/len(gate_means):.4f}")
        print(f"Gate std:  {sum(gate_stds)/len(gate_stds):.4f}")
    else:
        print("Gate not enabled in this model.")


@torch.no_grad()
def analyze_regimes(model, dataloader, device, max_batches=10):
    """Analyze regime usage statistics."""
    model.eval()
    all_indices = []

    for i, (x, _) in enumerate(dataloader):
        if i >= max_batches:
            break
        x = x.to(device)
        out = model(x)
        if out.regime_indices is not None:
            all_indices.append(out.regime_indices.cpu())

    if all_indices:
        indices = torch.cat(all_indices, dim=0).flatten()
        unique, counts = indices.unique(return_counts=True)
        total = counts.sum().item()
        print("Regime usage:")
        for u, c in sorted(zip(unique.tolist(), counts.tolist()), key=lambda x: -x[1]):
            print(f"  regime {u:>2d}: {c:>6d} ({100*c/total:.1f}%)")

        # Compute switch rate
        all_flat = torch.cat(all_indices, dim=0)
        switches = (all_flat[:, 1:] != all_flat[:, :-1]).float().mean()
        print(f"Switch rate: {switches:.4f}")
    else:
        print("Regime not enabled in this model.")


def main():
    parser = argparse.ArgumentParser(description="Evaluate LOLM")
    parser.add_argument("--checkpoint", type=str, required=True)
    parser.add_argument("--mode", choices=["perplexity", "generate", "gate", "regime", "all"],
                        default="all")
    parser.add_argument("--prompt", type=str, default="Once upon a time")
    parser.add_argument("--max_tokens", type=int, default=200)
    parser.add_argument("--temperature", type=float, default=0.8)
    args = parser.parse_args()

    # Load checkpoint
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    cfg = load_config(ckpt["config"])
    device = torch.device(cfg.training.device)

    model = LOLM(cfg.model).to(device)
    model.load_state_dict(ckpt["model"])
    print(f"Loaded checkpoint from step {ckpt['step']}")

    if args.mode in ("perplexity", "all"):
        print("\n--- Perplexity ---")
        val_loader = get_dataloader(
            cfg.data.dataset, cfg.data.cache_dir,
            cfg.training.seq_len, cfg.training.batch_size,
            split="validation",
        )
        ppl = compute_perplexity(model, val_loader, device)
        print(f"Validation perplexity: {ppl:.2f}")

    if args.mode in ("generate", "all"):
        print("\n--- Generation ---")
        text = generate(model, args.prompt, args.max_tokens,
                        args.temperature, device=str(device))
        print(text)

    if args.mode in ("gate", "all"):
        print("\n--- Gate Analysis ---")
        dl = get_dataloader(
            cfg.data.dataset, cfg.data.cache_dir,
            cfg.training.seq_len, cfg.training.batch_size,
        )
        analyze_gate(model, dl, device)

    if args.mode in ("regime", "all"):
        print("\n--- Regime Analysis ---")
        dl = get_dataloader(
            cfg.data.dataset, cfg.data.cache_dir,
            cfg.training.seq_len, cfg.training.batch_size,
        )
        analyze_regimes(model, dl, device)


if __name__ == "__main__":
    main()
