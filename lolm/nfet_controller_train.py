"""Training for the NFET control head — the self-improvement flywheel.

The control head (``graft.nfet.head``) maps ``[hidden(d), logit_entropy,
hidden_drift, gate_mean, regime_entropy]`` to five control actions. Nothing in
the token-loss graft training supervises it. This module gives it labels:

1. **Bootstrap (offline)** — distill the calibrated heuristic policy into the
   head. Telemetry comes from synthetic scenarios and/or real observable
   sequences recorded in the improvement log; hidden features are noise and
   their input weights are zeroed afterwards, so the bootstrapped head is
   exactly an observable-driven policy in network form.
2. **Replay (full fidelity)** — re-run logged text through the frozen
   backbone + graft to recover real hidden states, then train on the full
   feature vector. This is where the head can learn signals the heuristic
   cannot see. Requires the model, so it lives behind a flag.

Checkpoints saved here carry ``head_trained: true``, which the workspace uses
to let the head start overriding the heuristic decision-by-decision.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn.functional as F

from lolm.nfet_graft import LOLMNFETGraft
from lolm.nfet_policy import (
    CONTROL_LABELS,
    PolicyConfig,
    TelemetryFrame,
    frames_from_chat_trace,
    label_trace_decisions,
)

N_CONTROLS = len(CONTROL_LABELS)


# ---------------------------------------------------------------------------
# Telemetry sources
# ---------------------------------------------------------------------------

def synth_scenarios(n_sequences: int = 200, seq_len: int = 160,
                    seed: int = 0) -> List[List[TelemetryFrame]]:
    """Synthetic telemetry with injected events, mirroring real dynamics.

    Base levels follow what the live workspace produces (entropy in nats over
    a ~150k vocab, small drift, gate near 0.7, regime entropy of a 32-code
    detector). Each sequence carries 1-3 events: an entropy spike, a drift
    spike, a regime collapse, or a calm confident close.
    """
    rng = random.Random(seed)
    sequences: List[List[TelemetryFrame]] = []
    for _ in range(n_sequences):
        entropy_base = rng.uniform(2.4, 3.6)
        drift_base = rng.uniform(0.03, 0.08)
        gate_base = rng.uniform(0.6, 0.8)
        regime_base = rng.uniform(1.6, 2.6)
        frames: List[TelemetryFrame] = []
        events = rng.sample(
            ["entropy_spike", "drift_spike", "regime_collapse", "calm_close", "none"],
            k=rng.randint(1, 3),
        )
        spans: Dict[str, Tuple[int, int]] = {}
        cursor = seq_len // 3
        for event in events:
            if event in ("none",):
                continue
            start = rng.randint(cursor, max(cursor + 1, seq_len - 24))
            spans[event] = (start, min(start + rng.randint(8, 20), seq_len))
            cursor = min(spans[event][1] + 16, seq_len - 1)
        if "calm_close" in spans:  # calm close always runs to the end
            start = max(seq_len - rng.randint(16, 28), seq_len // 2)
            spans["calm_close"] = (start, seq_len)

        for i in range(seq_len):
            entropy = entropy_base + rng.gauss(0, 0.15)
            drift = max(drift_base + rng.gauss(0, 0.01), 0.0)
            gate = min(max(gate_base + rng.gauss(0, 0.02), 0.0), 1.0)
            regime = max(regime_base + rng.gauss(0, 0.1), 0.0)
            for event, (lo, hi) in spans.items():
                if lo <= i < hi:
                    if event == "entropy_spike":
                        entropy = entropy_base + rng.uniform(2.5, 4.0)
                    elif event == "drift_spike":
                        drift = drift_base + rng.uniform(0.4, 0.9)
                        entropy = entropy_base + rng.uniform(0.5, 1.2)
                    elif event == "regime_collapse":
                        regime = rng.uniform(0.05, 0.3)
                    elif event == "calm_close":
                        entropy = max(entropy_base - rng.uniform(1.6, 2.2), 0.2)
                        drift = max(drift_base - rng.uniform(0.02, 0.04), 0.005)
            frames.append(TelemetryFrame(
                logit_entropy=entropy, hidden_drift=drift, gate_mean=gate,
                regime_entropy=regime, step=i + 1,
            ))
        sequences.append(frames)
    return sequences


def load_log_sequences(path: Path) -> List[List[TelemetryFrame]]:
    """Real observable sequences from the workspace improvement log."""
    sequences: List[List[TelemetryFrame]] = []
    if not path.exists():
        return sequences
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        frames: List[TelemetryFrame] = []
        if event.get("type") == "chat" and isinstance(event.get("trace"), list):
            frames = frames_from_chat_trace(event["trace"])
        elif event.get("type") == "nfet_agent_run" and isinstance(event.get("frames"), list):
            frames = [
                TelemetryFrame(
                    logit_entropy=float(f.get("logit_entropy", 0.0)),
                    hidden_drift=float(f.get("hidden_drift", 0.0)),
                    gate_mean=float(f.get("gate_mean", 0.0)),
                    regime_entropy=float(f.get("regime_entropy", 0.0)),
                    step=int(f.get("step", i + 1)),
                )
                for i, f in enumerate(event["frames"])
                if isinstance(f, dict)
            ]
        if len(frames) >= 24:
            sequences.append(frames)
    return sequences


# ---------------------------------------------------------------------------
# Dataset construction
# ---------------------------------------------------------------------------

@dataclass
class ControlDataset:
    features: torch.Tensor      # (N, d_model + 4)
    labels: torch.Tensor        # (N,)
    class_counts: List[int]


def build_dataset(
    sequences: Sequence[Sequence[TelemetryFrame]],
    d_model: int,
    policy_config: Optional[PolicyConfig] = None,
    hidden: Optional[torch.Tensor] = None,
    hidden_noise_std: float = 0.0,
    skip_stateful_frames: bool = True,
    continue_keep_ratio: float = 0.05,
    seed: int = 0,
) -> ControlDataset:
    """Frames + weak labels -> per-token training rows.

    Feature layout matches ``NFETController.forward`` exactly:
    ``[hidden(d), logit_entropy, hidden_drift, gate_mean, regime_entropy]``.
    Frames whose label exists only because of run-state (cooldown/calibration)
    are dropped by default — a pointwise head cannot observe that state.
    ``continue_keep_ratio`` subsamples the dominant continue class.

    Bootstrap mode (no real ``hidden``) defaults to zeroed hidden features:
    the bootstrapped head is an observable-only function and its hidden
    columns are zeroed after training regardless, so training with noise there
    only drowns the four real features (fatal at d_model ~1024).
    """
    generator = torch.Generator().manual_seed(seed)
    rng = random.Random(seed)
    rows: List[torch.Tensor] = []
    labels: List[int] = []
    offset = 0
    for frames in sequences:
        decisions = label_trace_decisions(frames, policy_config)
        for i, (frame, decision) in enumerate(zip(frames, decisions)):
            if skip_stateful_frames and decision.source in ("cooldown", "calibrating"):
                continue
            if decision.control == 0 and rng.random() > continue_keep_ratio:
                continue
            if hidden is not None:
                h = hidden[offset + i]
            elif hidden_noise_std > 0:
                h = torch.randn(d_model, generator=generator) * hidden_noise_std
            else:
                h = torch.zeros(d_model)
            obs = torch.tensor([
                frame.logit_entropy, frame.hidden_drift,
                frame.gate_mean, frame.regime_entropy,
            ], dtype=torch.float32)
            rows.append(torch.cat([h.float(), obs]))
            labels.append(decision.control)
        offset += len(frames)
    if not rows:
        raise ValueError("No training rows produced — need longer traces or more sequences.")
    features = torch.stack(rows)
    label_tensor = torch.tensor(labels, dtype=torch.long)
    counts = [int((label_tensor == c).sum()) for c in range(N_CONTROLS)]
    return ControlDataset(features=features, labels=label_tensor, class_counts=counts)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_control_head(
    graft: LOLMNFETGraft,
    dataset: ControlDataset,
    epochs: int = 8,
    lr: float = 1e-3,
    batch_size: int = 256,
    weight_decay: float = 1e-2,
    holdout_fraction: float = 0.2,
    zero_hidden_weights: bool = True,
    device: Optional[torch.device] = None,
    seed: int = 0,
) -> Dict[str, object]:
    """Train only ``graft.nfet.head`` with class-weighted cross-entropy.

    ``zero_hidden_weights=True`` (bootstrap mode) zeroes the first-layer
    columns that read the hidden vector, making the trained head a pure
    function of the four observables — exactly the distilled heuristic.
    Replay training should pass ``zero_hidden_weights=False``.
    """
    device = device or torch.device("cpu")
    head = graft.nfet.head.to(device)
    for param in graft.parameters():
        param.requires_grad_(False)
    for param in head.parameters():
        param.requires_grad_(True)

    n = dataset.features.size(0)
    perm = torch.randperm(n, generator=torch.Generator().manual_seed(seed))
    holdout = max(int(n * holdout_fraction), 1)
    val_idx, train_idx = perm[:holdout], perm[holdout:]
    x_train = dataset.features[train_idx].to(device)
    y_train = dataset.labels[train_idx].to(device)
    x_val = dataset.features[val_idx].to(device)
    y_val = dataset.labels[val_idx].to(device)

    counts = torch.tensor(dataset.class_counts, dtype=torch.float32).clamp_min(1)
    weights = (counts.sum() / (N_CONTROLS * counts)).clamp(0.1, 20.0).to(device)

    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=weight_decay)
    history: List[Dict[str, float]] = []
    for epoch in range(epochs):
        head.train()
        order = torch.randperm(x_train.size(0), generator=torch.Generator().manual_seed(seed + epoch))
        total = 0.0
        batches = 0
        for start in range(0, x_train.size(0), batch_size):
            idx = order[start:start + batch_size]
            logits = head(x_train[idx])
            loss = F.cross_entropy(logits, y_train[idx], weight=weights)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total += float(loss.detach())
            batches += 1
        head.eval()
        with torch.no_grad():
            val_logits = head(x_val)
            val_loss = float(F.cross_entropy(val_logits, y_val, weight=weights))
            val_acc = float((val_logits.argmax(dim=-1) == y_val).float().mean())
        history.append({"epoch": epoch + 1, "train_loss": total / max(batches, 1),
                        "val_loss": val_loss, "val_acc": val_acc})

    if zero_hidden_weights:
        with torch.no_grad():
            first_linear = head[0]
            d_model = first_linear.in_features - 4
            first_linear.weight[:, :d_model].zero_()

    head.eval()
    with torch.no_grad():
        val_logits = head(x_val)
        final_acc = float((val_logits.argmax(dim=-1) == y_val).float().mean())
        per_class: Dict[str, float] = {}
        for c in range(N_CONTROLS):
            mask = y_val == c
            if int(mask.sum()) > 0:
                per_class[CONTROL_LABELS[c]] = float(
                    (val_logits[mask].argmax(dim=-1) == c).float().mean()
                )
    return {
        "history": history,
        "val_acc": final_acc,
        "per_class_recall": per_class,
        "train_rows": int(x_train.size(0)),
        "val_rows": int(x_val.size(0)),
        "class_counts": dataset.class_counts,
        "zeroed_hidden_weights": zero_hidden_weights,
    }


def save_controller_checkpoint(graft: LOLMNFETGraft, path: Path,
                               metrics: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "graft": graft.state_dict(),
        "head_trained": True,
        "controller_metrics": metrics,
    }, path)
