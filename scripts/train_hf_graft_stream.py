#!/usr/bin/env python3
"""Streaming trainer for a frozen HF backbone plus LOLM-NFET graft."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch.optim import AdamW
from tqdm import tqdm

from lolm.graft_train_step import graft_train_step
from lolm.hf_backbone import FrozenHFBackbone
from lolm.nfet_graft import LOLMNFETGraft
from lolm.text_stream import iter_text_batches, open_text_stream


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="qwen3_0_6b_smoke")
    p.add_argument("--registry", default="configs/hf_models.yaml")
    p.add_argument("--dataset", default="HuggingFaceFW/fineweb-edu")
    p.add_argument("--dataset-config", default=None)
    p.add_argument("--split", default="train")
    p.add_argument("--text-field", default="text")
    p.add_argument("--steps", type=int, default=100)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--seq-len", type=int, default=256)
    p.add_argument("--shuffle-buffer", type=int, default=10_000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--grad-clip", type=float, default=1.0)
    p.add_argument("--device", default=None)
    p.add_argument("--latent-backend", default="selective_ssm", choices=["selective_ssm", "gru_debug"])
    p.add_argument("--ssm-layers", type=int, default=1)
    p.add_argument("--ssm-d-state", type=int, default=16)
    p.add_argument("--ssm-expand", type=int, default=1)
    p.add_argument("--out", default="runs/hf_graft_stream/ckpt.pt")
    p.add_argument("--log-every", type=int, default=10)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    torch.manual_seed(args.seed)
    device = torch.device(args.device) if args.device else None

    backbone = FrozenHFBackbone.from_registry(args.profile, args.registry, freeze=True)
    if device is not None:
        try:
            backbone.to(device)
        except RuntimeError as exc:
            print(f"warning: could not move backbone to {device}: {exc}")

    graft = LOLMNFETGraft(
        d_model=backbone.hidden_size,
        latent_backend=args.latent_backend,
        ssm_layers=args.ssm_layers,
        ssm_d_state=args.ssm_d_state,
        ssm_expand=args.ssm_expand,
    )
    if device is not None:
        graft.to(device)
    graft.train()

    opt = AdamW(graft.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    stream = open_text_stream(
        dataset=args.dataset,
        split=args.split,
        dataset_config=args.dataset_config,
        seed=args.seed,
        shuffle_buffer=args.shuffle_buffer,
    )
    text_iter = iter_text_batches(stream, text_field=args.text_field, batch_size=args.batch_size)

    history = []
    for step in tqdm(range(1, args.steps + 1), desc="hf-graft-stream"):
        texts = next(text_iter)
        batch = backbone.tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=args.seq_len)
        if device is not None:
            batch = {k: v.to(device) for k, v in batch.items()}
        row = graft_train_step(backbone, graft, batch, opt, grad_clip=args.grad_clip)
        row["step"] = step
        history.append(row)
        if step == 1 or step % args.log_every == 0:
            print(json.dumps(row))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = vars(args).copy()
    metadata["model_id"] = backbone.profile.model_id
    metadata["hidden_size"] = backbone.hidden_size
    torch.save({"graft": graft.state_dict(), "history": history, "metadata": metadata}, out_path)
    print(json.dumps({"saved": str(out_path), "steps": args.steps}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
