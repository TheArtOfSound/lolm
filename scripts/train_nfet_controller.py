"""Train the NFET control head so it can take over the agent loop.

Bootstrap (no model download, runs anywhere):
    PYTHONPATH=. python scripts/train_nfet_controller.py --synthetic 300 \
        --out runs/nfet_controller/ckpt.pt

Bootstrap from real workspace traffic (observables from the improvement log):
    PYTHONPATH=. python scripts/train_nfet_controller.py \
        --log local_ui/data/improvement_log.jsonl --synthetic 100 \
        --out runs/nfet_controller/ckpt.pt

Full-fidelity replay through the frozen backbone (downloads the model):
    PYTHONPATH=. python scripts/train_nfet_controller.py \
        --replay local_ui/data/improvement_log.jsonl --profile qwen3_0_6b_smoke \
        --out runs/nfet_controller/ckpt.pt

Load the result in the workspace via the model loader's graft checkpoint field;
the server flips `head_trained` on and the head starts overriding the
heuristic whenever it is confident.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional, Tuple

import torch

from lolm.nfet_controller_train import (
    build_dataset,
    load_log_sequences,
    outcome_examples,
    save_controller_checkpoint,
    synth_scenarios,
    train_control_head,
)
from lolm.nfet_graft import LOLMNFETGraft
from lolm.nfet_policy import TelemetryFrame


def entropy_rows(logits: torch.Tensor) -> torch.Tensor:
    log_probs = torch.log_softmax(logits.float(), dim=-1)
    return -(log_probs.exp() * log_probs).sum(dim=-1)


def replay_through_model(
    log_path: Path, profile: str, registry: str, device: torch.device,
    latent_backend: str, checkpoint_in: Optional[str], max_seq: int, max_sequences: int,
) -> Tuple[List[List[TelemetryFrame]], torch.Tensor, LOLMNFETGraft]:
    """Re-run logged text through backbone + graft for full-feature training."""
    from lolm.hf_backbone import FrozenHFBackbone

    backbone = FrozenHFBackbone.from_registry(profile, registry, freeze=True)
    backbone.to(device)
    graft = LOLMNFETGraft(d_model=backbone.hidden_size, latent_backend=latent_backend)  # type: ignore[arg-type]
    if checkpoint_in:
        ckpt = torch.load(checkpoint_in, map_location="cpu")
        graft.load_state_dict(ckpt["graft"])
    graft.to(device).eval()

    texts: List[str] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") in ("chat", "nfet_agent_run"):
            prompt = event.get("prompt") or event.get("command") or ""
            response = event.get("response") or ""
            text = f"{prompt}\n{response}".strip()
            if len(text.split()) >= 24:
                texts.append(text)
        if len(texts) >= max_sequences:
            break
    if not texts:
        raise SystemExit(f"No replayable entries in {log_path}")

    sequences: List[List[TelemetryFrame]] = []
    hidden_rows: List[torch.Tensor] = []
    with torch.no_grad():
        for text in texts:
            batch = backbone.tokenizer(text, return_tensors="pt", truncation=True,
                                       max_length=max_seq)
            batch = {k: v.to(device) for k, v in batch.items()}
            base = backbone(**batch)
            out = graft(base.hidden_states, base_logits=base.logits)
            corrected = out.corrected_hidden[0]                      # (T, d)
            entropy = entropy_rows(base.logits[0])                   # (T,)
            gate = out.gate[0].float().mean(dim=-1)                  # (T,)
            probs = out.regime_probs[0].float().clamp_min(1e-8)
            regime = -(probs * probs.log()).sum(dim=-1)              # (T,)
            drift = torch.zeros_like(entropy)
            drift[1:] = (corrected[1:].float() - corrected[:-1].float()).pow(2).mean(dim=-1)
            frames = [
                TelemetryFrame(
                    logit_entropy=float(entropy[t]), hidden_drift=float(drift[t]),
                    gate_mean=float(gate[t]), regime_entropy=float(regime[t]), step=t + 1,
                )
                for t in range(corrected.size(0))
            ]
            sequences.append(frames)
            hidden_rows.append(corrected.float().cpu())
    hidden = torch.cat(hidden_rows, dim=0)
    return sequences, hidden, graft


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", type=int, default=0, help="number of synthetic scenario sequences")
    parser.add_argument("--log", type=str, default="", help="improvement_log.jsonl with real observable traces")
    parser.add_argument("--outcomes", type=str, default="", help="improvement_log.jsonl to mine receipt-labeled decisions from (flywheel turn two)")
    parser.add_argument("--replay", type=str, default="", help="improvement log to replay through the model (full features)")
    parser.add_argument("--profile", type=str, default="qwen3_0_6b_smoke")
    parser.add_argument("--registry", type=str, default="configs/hf_models.yaml")
    parser.add_argument("--d-model", type=int, default=1024, help="hidden size when training without a backbone (Qwen3-0.6B: 1024)")
    parser.add_argument("--latent-backend", type=str, default="gru_debug")
    parser.add_argument("--checkpoint-in", type=str, default="", help="existing graft checkpoint to start from")
    parser.add_argument("--out", type=str, default="runs/nfet_controller/ckpt.pt")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--continue-keep-ratio", type=float, default=0.25)
    parser.add_argument("--max-seq", type=int, default=512)
    parser.add_argument("--max-sequences", type=int, default=64)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    device = torch.device(args.device)

    if args.replay:
        if args.synthetic or args.log:
            raise SystemExit("--replay is exclusive: it trains on full features from the model.")
        sequences, hidden, graft = replay_through_model(
            Path(args.replay), args.profile, args.registry, device,
            args.latent_backend, args.checkpoint_in or None,
            args.max_seq, args.max_sequences,
        )
        dataset = build_dataset(sequences, d_model=hidden.size(-1), hidden=hidden,
                                continue_keep_ratio=args.continue_keep_ratio, seed=args.seed)
        zero_hidden = False
    else:
        sequences = []
        if args.synthetic:
            sequences.extend(synth_scenarios(args.synthetic, seed=args.seed))
        if args.log:
            log_sequences = load_log_sequences(Path(args.log))
            print(f"loaded {len(log_sequences)} telemetry sequences from {args.log}")
            sequences.extend(log_sequences)
        extras = []
        if args.outcomes:
            extras = outcome_examples(Path(args.outcomes))
            print(f"mined {len(extras)} receipt-labeled decision rows from {args.outcomes}")
        if not sequences and not extras:
            raise SystemExit("Nothing to train on: pass --synthetic N and/or --log PATH (or --replay).")
        graft = LOLMNFETGraft(d_model=args.d_model, latent_backend=args.latent_backend)  # type: ignore[arg-type]
        if args.checkpoint_in:
            ckpt = torch.load(args.checkpoint_in, map_location="cpu")
            graft.load_state_dict(ckpt["graft"])
        dataset = build_dataset(sequences, d_model=args.d_model,
                                continue_keep_ratio=args.continue_keep_ratio, seed=args.seed,
                                extra_examples=extras)
        zero_hidden = True

    metrics = train_control_head(
        graft, dataset, epochs=args.epochs, lr=args.lr, batch_size=args.batch_size,
        zero_hidden_weights=zero_hidden, device=device, seed=args.seed,
    )
    out_path = Path(args.out)
    save_controller_checkpoint(graft, out_path, metrics)
    print(json.dumps({
        "saved": str(out_path),
        "head_trained": True,
        "mode": "replay" if args.replay else "bootstrap",
        "val_acc": metrics["val_acc"],
        "per_class_recall": metrics["per_class_recall"],
        "class_counts": metrics["class_counts"],
        "rows": {"train": metrics["train_rows"], "val": metrics["val_rows"]},
    }, indent=2))


if __name__ == "__main__":
    main()
