#!/usr/bin/env python3
"""Compare frozen base LM against the LOLM-NFET graft on identical text.

This is the minimum honest loop: base loss vs graft loss, same model, same text,
same LM head. The graft only wins if corrected hidden states reduce token loss.
"""

from __future__ import annotations

import argparse
import json

import torch

from lolm.hf_backbone import FrozenHFBackbone
from lolm.hf_lm_head import project_with_backbone_lm_head, shifted_language_model_loss
from lolm.nfet_graft import LOLMNFETGraft


DEFAULT_TEXTS = [
    "The central claim is that language contains slow latent order beneath local token prediction.",
    "A useful architecture must improve controlled metrics, not merely produce a better story.",
    "The model should recover when a plan changes, a tool fails, or context creates contradiction.",
    "Regime codes only matter if they align with meaningful phase changes and survive ablation.",
]

ABLATIONS = ["full", "no_latent", "no_regime", "no_gate", "latent_only", "no_residual"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="qwen3_0_6b_smoke")
    parser.add_argument("--registry", default="configs/hf_models.yaml")
    parser.add_argument("--checkpoint", default=None, help="Optional graft checkpoint from train_hf_graft_tiny.py")
    parser.add_argument("--text", action="append", default=[], help="Text to evaluate; can be passed multiple times")
    parser.add_argument("--seq-len", type=int, default=128)
    parser.add_argument("--device", default=None)
    parser.add_argument("--latent-backend", default="selective_ssm", choices=["selective_ssm", "gru_debug"])
    parser.add_argument("--ablations", action="store_true", help="Report all graft ablations")
    return parser.parse_args()


def scalar(x: torch.Tensor) -> float:
    return float(x.detach().float().cpu().item())


def main() -> int:
    args = parse_args()
    device = torch.device(args.device) if args.device else None
    texts = args.text or DEFAULT_TEXTS

    backbone = FrozenHFBackbone.from_registry(args.profile, args.registry, freeze=True)
    if device is not None:
        try:
            backbone.to(device)
        except RuntimeError as exc:
            print(f"warning: could not move backbone to {device}: {exc}")

    graft = LOLMNFETGraft(d_model=backbone.hidden_size, latent_backend=args.latent_backend)
    if args.checkpoint:
        ckpt = torch.load(args.checkpoint, map_location="cpu")
        graft.load_state_dict(ckpt["graft"])
    if device is not None:
        graft.to(device)
    graft.eval()

    modes = ABLATIONS if args.ablations else ["full"]
    rows = []
    with torch.no_grad():
        for text in texts:
            batch = backbone.tokenizer(text, return_tensors="pt", truncation=True, max_length=args.seq_len)
            if device is not None:
                batch = {k: v.to(device) for k, v in batch.items()}
            labels = batch["input_ids"].clone()
            base = backbone(**batch)
            base_loss = shifted_language_model_loss(base.logits, labels)
            for mode in modes:
                out = graft(base.hidden_states, base_logits=base.logits, ablation_mode=mode)
                graft_logits = project_with_backbone_lm_head(backbone.model, out.corrected_hidden)
                graft_loss = shifted_language_model_loss(graft_logits, labels)
                row = {
                    "text": text,
                    "mode": mode,
                    "base_loss": scalar(base_loss),
                    "graft_loss": scalar(graft_loss),
                    "delta": scalar(graft_loss - base_loss),
                    "gate_mean": scalar(out.gate.mean()),
                    "regime_entropy": scalar(out.nfet_state.regime_entropy.mean()),
                    "control": out.nfet_state.control_logits.argmax(dim=-1).detach().cpu().tolist(),
                }
                rows.append(row)
                print(json.dumps(row))

    summary = {}
    for mode in modes:
        subset = [row for row in rows if row["mode"] == mode]
        avg_base = sum(row["base_loss"] for row in subset) / len(subset)
        avg_graft = sum(row["graft_loss"] for row in subset) / len(subset)
        summary[mode] = {"avg_base_loss": avg_base, "avg_graft_loss": avg_graft, "avg_delta": avg_graft - avg_base}
    print(json.dumps({"summary": summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
