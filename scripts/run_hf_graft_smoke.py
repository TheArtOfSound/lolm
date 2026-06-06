#!/usr/bin/env python3
"""Smoke-test the LOLM-NFET graft on a Hugging Face checkpoint.

This verifies:
  - selected HF checkpoint loads
  - tokenizer works
  - hidden states are exposed
  - LOLM-NFET graft runs
  - NFET observables are produced

Run:
  python scripts/run_hf_graft_smoke.py --profile qwen3_0_6b_smoke
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

import torch

from lolm.hf_backbone import FrozenHFBackbone
from lolm.nfet_graft import LOLMNFETGraft, graft_regularization_loss


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a LOLM-NFET HF graft smoke test")
    parser.add_argument("--profile", default="qwen3_0_6b_smoke", help="Profile name from configs/hf_models.yaml")
    parser.add_argument("--registry", default="configs/hf_models.yaml", help="Registry YAML path")
    parser.add_argument("--text", default="LOLM-NFET should track latent order beneath the surface of language.")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--device", default=None, help="Optional torch device override, e.g. cuda, mps, cpu")
    return parser.parse_args()


def tensor_scalar(value: torch.Tensor) -> float:
    return float(value.detach().float().cpu().item())


def main() -> int:
    args = parse_args()
    device = torch.device(args.device) if args.device else None

    backbone = FrozenHFBackbone.from_registry(profile_name=args.profile, registry_path=args.registry, freeze=True)
    if device is not None:
        # device_map=auto can already shard the model; this move is for small/local models only.
        try:
            backbone.to(device)
        except RuntimeError as exc:
            print(f"warning: could not move backbone to {device}: {exc}")

    batch = backbone.tokenize(args.text, device=device)
    if batch["input_ids"].size(1) > args.max_tokens:
        batch = {key: value[:, : args.max_tokens] for key, value in batch.items()}

    with torch.no_grad():
        base = backbone(**batch)

    graft = LOLMNFETGraft(d_model=backbone.hidden_size)
    if device is not None:
        graft.to(device)
    graft.train()
    out = graft(base.hidden_states.detach(), base_logits=base.logits.detach())
    reg_losses = graft_regularization_loss(out)

    summary: Dict[str, Any] = {
        "profile": args.profile,
        "model_id": backbone.profile.model_id,
        "hidden_size": backbone.hidden_size,
        "input_shape": list(batch["input_ids"].shape),
        "base_logits_shape": list(base.logits.shape),
        "corrected_hidden_shape": list(out.corrected_hidden.shape),
        "gate_mean": tensor_scalar(out.gate.mean()),
        "regime_entropy": tensor_scalar(out.nfet_state.regime_entropy.mean()),
        "hidden_drift": tensor_scalar(out.nfet_state.hidden_drift.mean()),
        "logit_entropy": tensor_scalar(out.nfet_state.logit_entropy.mean()),
        "control_logits_shape": list(out.nfet_state.control_logits.shape),
        "regularization": {key: tensor_scalar(value) for key, value in reg_losses.items()},
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
