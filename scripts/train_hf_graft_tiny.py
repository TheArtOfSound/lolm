#!/usr/bin/env python3
"""Tiny training loop for the Hugging Face LOLM-NFET graft.

This is deliberately minimal. It freezes the HF backbone, trains only the graft,
and computes next-token loss through the base model LM head.

Run:
  python scripts/train_hf_graft_tiny.py --profile qwen3_0_6b_smoke --steps 20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch.optim import AdamW

from lolm.hf_backbone import FrozenHFBackbone
from lolm.hf_lm_head import project_with_backbone_lm_head, shifted_language_model_loss
from lolm.nfet_graft import LOLMNFETGraft, graft_regularization_loss


TEXTS = [
    "Language is not only token prediction; it contains latent order across time.",
    "A model that tracks discourse phase should recover better from long-horizon drift.",
    "NFET controls when a system continues, verifies, retrieves, branches, or stops.",
    "The useful experiment is base versus base plus graft under matched conditions.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="qwen3_0_6b_smoke")
    parser.add_argument("--registry", default="configs/hf_models.yaml")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--seq-len", type=int, default=96)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--device", default=None)
    parser.add_argument("--latent-backend", default="selective_ssm", choices=["selective_ssm", "gru_debug"])
    parser.add_argument("--out", default="runs/hf_graft_tiny/ckpt.pt")
    return parser.parse_args()


def make_batch(backbone: FrozenHFBackbone, step: int, seq_len: int, device: torch.device | None):
    text = TEXTS[step % len(TEXTS)]
    batch = backbone.tokenizer(text, return_tensors="pt", truncation=True, max_length=seq_len)
    if batch["input_ids"].size(1) < 4:
        raise ValueError("Tokenized sequence too short")
    if device is not None:
        batch = {k: v.to(device) for k, v in batch.items()}
    labels = batch["input_ids"].clone()
    return batch, labels


def scalar(x: torch.Tensor) -> float:
    return float(x.detach().float().cpu().item())


def main() -> int:
    args = parse_args()
    device = torch.device(args.device) if args.device else None

    backbone = FrozenHFBackbone.from_registry(args.profile, args.registry, freeze=True)
    if device is not None:
        try:
            backbone.to(device)
        except RuntimeError as exc:
            print(f"warning: could not move backbone to {device}: {exc}")

    graft = LOLMNFETGraft(d_model=backbone.hidden_size, latent_backend=args.latent_backend)
    if device is not None:
        graft.to(device)
    graft.train()

    opt = AdamW(graft.parameters(), lr=args.lr, weight_decay=0.01)
    history = []

    for step in range(1, args.steps + 1):
        batch, labels = make_batch(backbone, step, args.seq_len, device)
        with torch.no_grad():
            base = backbone(**batch)
        out = graft(base.hidden_states.detach(), base_logits=base.logits.detach())
        logits = project_with_backbone_lm_head(backbone.model, out.corrected_hidden)
        token_loss = shifted_language_model_loss(logits, labels)
        aux = graft_regularization_loss(out)
        loss = (
            token_loss
            + 0.02 * aux["regime_token_entropy_reward"]
            + 0.05 * aux["regime_usage_entropy_reward"]
            + 0.01 * aux["gate_balance"]
            + 0.001 * aux["residual_l2"]
        )
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(graft.parameters(), 1.0)
        opt.step()

        row = {
            "step": step,
            "loss": scalar(loss),
            "token_loss": scalar(token_loss),
            "gate_mean": scalar(out.gate.mean()),
            "regime_entropy": scalar(out.nfet_state.regime_entropy.mean()),
            "hidden_drift": scalar(out.nfet_state.hidden_drift.mean()),
        }
        history.append(row)
        print(json.dumps(row))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"graft": graft.state_dict(), "history": history, "profile": args.profile}, out_path)
    print(json.dumps({"saved": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
