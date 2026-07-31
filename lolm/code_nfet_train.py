# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Train a *coding-specific* NFET control head from synthetic scenarios + receipts.

Unlike the chat control head (graft.nfet.head over d_model+4), the coding head
is a small MLP over **coding-relevant features**:

    [entropy, drift, gate, regime,
     thrash_norm, green_frac, fail_frac, contract_failed, exit_ok]

Labels come from:
  1. Distilled coding-tuned heuristic (synthetic coding dynamics)
  2. Outcome labels mined from sealed code receipts (shipped / stuck / thrash)
  3. Optional NFET timelines already written into receipts after CodeNFET shipped

The head is pure observables — no backbone required — so it trains in seconds
on CPU and deploys next to CodeNFET without torch at inference (we still use
torch for train; inference can use numpy/math softmax).
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from lolm.nfet_policy import (
    CONTROL_BRANCH,
    CONTROL_CONTINUE,
    CONTROL_FINALIZE,
    CONTROL_LABELS,
    CONTROL_RETRIEVE,
    CONTROL_VERIFY,
    NFETControlPolicy,
    TelemetryFrame,
)
from local_ui.code_nfet import _CODE_POLICY, _synthetic_frames

N_CONTROLS = 5
N_FEATURES = 9  # entropy,drift,gate,regime,thrash,green,fail,contract,exit


class CodingControlHead(nn.Module):
    """Tiny MLP: coding features → 5 control logits."""

    def __init__(self, n_in: int = N_FEATURES, hidden: int = 32):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_in, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, N_CONTROLS),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def _feat(
    entropy: float, drift: float, gate: float, regime: float,
    thrash: int = 0, green: int = 0, failed: int = 0,
    contract_failed: bool = False, exit_ok: bool = False,
) -> List[float]:
    total = max(green + failed, 1)
    return [
        float(entropy),
        float(drift),
        float(gate),
        float(regime),
        min(float(thrash), 5.0) / 5.0,
        float(green) / total,
        float(failed) / total,
        1.0 if contract_failed else 0.0,
        1.0 if exit_ok else 0.0,
    ]


def synth_coding_examples(n: int = 800, seed: int = 0) -> List[Tuple[List[float], int, float]]:
    """Generate (features, label, weight) for coding control scenarios."""
    rng = random.Random(seed)
    rows: List[Tuple[List[float], int, float]] = []
    scenarios = [
        "fail_once", "thrash", "contract_red", "green_ship",
        "syntax_flail", "retrieve_need", "calm_progress",
    ]
    for i in range(n):
        kind = scenarios[i % len(scenarios)]
        if kind == "fail_once":
            frames = _synthetic_frames(
                exit_ok=False, thrash=0, green_runs=0, failed_runs=1,
                stderr="AssertionError", contract_failed=False, budget_frac=0.2,
            )
            thrash, green, failed, cfail, eok = 0, 0, 1, False, False
            label, w = CONTROL_VERIFY, 1.2
        elif kind == "thrash":
            frames = _synthetic_frames(
                exit_ok=False, thrash=2, green_runs=0, failed_runs=3,
                stderr="AssertionError", contract_failed=False, budget_frac=0.6,
            )
            thrash, green, failed, cfail, eok = 2, 0, 3, False, False
            label, w = CONTROL_BRANCH, 1.8
        elif kind == "contract_red":
            frames = _synthetic_frames(
                exit_ok=True, thrash=0, green_runs=2, failed_runs=0,
                stderr="", contract_failed=True, budget_frac=0.3,
            )
            thrash, green, failed, cfail, eok = 0, 2, 0, True, True
            label, w = CONTROL_VERIFY, 1.6
        elif kind == "green_ship":
            frames = _synthetic_frames(
                exit_ok=True, thrash=0, green_runs=3, failed_runs=0,
                stderr="", contract_failed=False, budget_frac=0.2,
            )
            thrash, green, failed, cfail, eok = 0, 3, 0, False, True
            label, w = CONTROL_FINALIZE, 1.5
        elif kind == "syntax_flail":
            frames = _synthetic_frames(
                exit_ok=False, thrash=1, green_runs=0, failed_runs=2,
                stderr="SyntaxError: invalid syntax", contract_failed=False,
                budget_frac=0.4,
            )
            thrash, green, failed, cfail, eok = 1, 0, 2, False, False
            label, w = CONTROL_VERIFY, 1.1
        elif kind == "retrieve_need":
            frames = _synthetic_frames(
                exit_ok=False, thrash=0, green_runs=0, failed_runs=1,
                stderr="ModuleNotFoundError", contract_failed=False, budget_frac=0.15,
            )
            thrash, green, failed, cfail, eok = 0, 0, 1, False, False
            label, w = CONTROL_RETRIEVE, 1.3
        else:  # calm_progress
            frames = _synthetic_frames(
                exit_ok=True, thrash=0, green_runs=1, failed_runs=1,
                stderr="", contract_failed=False, budget_frac=0.35,
            )
            thrash, green, failed, cfail, eok = 0, 1, 1, False, True
            label, w = CONTROL_CONTINUE, 0.8

        # Use mean of synthetic frames as the obs vector.
        e = sum(f.logit_entropy for f in frames) / len(frames)
        d = sum(f.hidden_drift for f in frames) / len(frames)
        g = sum(f.gate_mean for f in frames) / len(frames)
        r = sum(f.regime_entropy for f in frames) / len(frames)
        # Small noise so the head generalizes.
        e += rng.gauss(0, 0.05)
        d = max(0.0, d + rng.gauss(0, 0.01))
        rows.append((_feat(e, d, g, r, thrash, green, failed, cfail, eok), label, w))
    return rows


def distill_coding_policy(n: int = 400, seed: int = 1) -> List[Tuple[List[float], int, float]]:
    """Replay the coding-tuned NFETControlPolicy over synthetic frames; distill."""
    rng = random.Random(seed)
    rows: List[Tuple[List[float], int, float]] = []
    for i in range(n):
        exit_ok = rng.random() > 0.45
        thrash = rng.randint(0, 3) if not exit_ok else 0
        green = rng.randint(0, 4)
        failed = rng.randint(0, 4) if not exit_ok else rng.randint(0, 1)
        cfail = (not exit_ok) and rng.random() > 0.7 or (exit_ok and rng.random() > 0.85)
        frames = _synthetic_frames(
            exit_ok=exit_ok, thrash=thrash, green_runs=green, failed_runs=failed,
            stderr="AssertionError" if not exit_ok else "",
            contract_failed=cfail, budget_frac=rng.random(),
        )
        policy = NFETControlPolicy(_CODE_POLICY)
        policy.observe_all(frames)
        decision = policy.decide(control_logits=None, head_trained=False)
        # Apply same coding guards as CodeNFET (so the head learns them).
        label = decision.control
        if thrash >= 2:
            label = CONTROL_BRANCH
        elif cfail and exit_ok:
            label = CONTROL_VERIFY
        elif not exit_ok and label == CONTROL_FINALIZE:
            label = CONTROL_VERIFY if thrash < 2 else CONTROL_BRANCH
        elif exit_ok and not cfail and thrash == 0 and green >= 2:
            label = CONTROL_FINALIZE
        e = sum(f.logit_entropy for f in frames) / len(frames)
        d = sum(f.hidden_drift for f in frames) / len(frames)
        g = sum(f.gate_mean for f in frames) / len(frames)
        r = sum(f.regime_entropy for f in frames) / len(frames)
        rows.append((_feat(e, d, g, r, thrash, green, failed, cfail, exit_ok),
                     label, 1.0))
    return rows


def mine_code_receipts(path: Path) -> List[Tuple[List[float], int, float]]:
    """Outcome-supervised rows from sealed code receipts."""
    rows: List[Tuple[List[float], int, float]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        # Prefer receipts that already carry an NFET timeline.
        nfet = rec.get("nfet") or {}
        timeline = nfet.get("timeline") if isinstance(nfet, dict) else None
        ok = bool(rec.get("ok") or rec.get("verdict") in ("shipped", "verified"))
        stuck = bool(rec.get("stuck"))
        green = int(rec.get("green_runs") or 0)
        failed = int(rec.get("failed_runs") or 0)
        thrash = 2 if stuck else (1 if failed >= 3 else 0)

        if isinstance(timeline, list) and timeline:
            for entry in timeline:
                if not isinstance(entry, dict):
                    continue
                lab = entry.get("label")
                if lab not in CONTROL_LABELS.values():
                    continue
                # reverse map label -> id
                label = next(k for k, v in CONTROL_LABELS.items() if v == lab)
                me = entry.get("mean_entropy")
                e = float(me) if me is not None else (2.8 if not ok else 1.4)
                # Rough defaults when only label is known.
                d = 0.2 if not ok else 0.05
                g = 0.7
                r = 0.5 if thrash >= 2 else 1.5
                cfail = bool(entry.get("force_verify") and ok)
                eok = bool(entry.get("force_verify") is False and ok) or ok
                # Weight outcome-aligned labels higher.
                w = 1.4 if (ok and label == CONTROL_FINALIZE) or (stuck and label == CONTROL_BRANCH) else 1.0
                rows.append((_feat(e, d, g, r, thrash, green, failed, cfail, eok), label, w))
            continue

        # No timeline: label the *end state* of the receipt.
        if ok:
            rows.append((_feat(1.2, 0.04, 0.55, 1.6, 0, max(green, 1), failed, False, True),
                         CONTROL_FINALIZE, 1.3))
        elif stuck or failed >= 3:
            rows.append((_feat(3.4, 0.25, 0.85, 0.45, 2, green, max(failed, 2), False, False),
                         CONTROL_BRANCH, 1.5))
        elif failed > 0:
            rows.append((_feat(2.9, 0.18, 0.75, 1.0, 0, green, failed, False, False),
                         CONTROL_VERIFY, 1.1))
    return rows


@dataclass
class TrainResult:
    path: Path
    train_acc: float
    val_acc: float
    n_rows: int
    class_counts: List[int]
    epochs: int


def train_coding_head(
    out: Path,
    *,
    synthetic: int = 800,
    distill: int = 400,
    receipt_paths: Optional[Sequence[Path]] = None,
    epochs: int = 40,
    lr: float = 2e-3,
    seed: int = 0,
) -> TrainResult:
    rows: List[Tuple[List[float], int, float]] = []
    rows.extend(synth_coding_examples(synthetic, seed=seed))
    rows.extend(distill_coding_policy(distill, seed=seed + 1))
    for p in receipt_paths or []:
        rows.extend(mine_code_receipts(Path(p)))

    if len(rows) < 32:
        raise ValueError(f"need more training rows, got {len(rows)}")

    rng = random.Random(seed)
    rng.shuffle(rows)
    xs = torch.tensor([r[0] for r in rows], dtype=torch.float32)
    ys = torch.tensor([r[1] for r in rows], dtype=torch.long)
    ws = torch.tensor([r[2] for r in rows], dtype=torch.float32)

    n = xs.size(0)
    hold = max(int(n * 0.2), 8)
    x_val, y_val = xs[:hold], ys[:hold]
    x_tr, y_tr, w_tr = xs[hold:], ys[hold:], ws[hold:]

    counts = torch.bincount(ys, minlength=N_CONTROLS).float().clamp_min(1)
    class_w = (counts.sum() / (N_CONTROLS * counts)).clamp(0.2, 8.0)

    model = CodingControlHead()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)

    def acc(pred: torch.Tensor, y: torch.Tensor) -> float:
        return float((pred.argmax(-1) == y).float().mean())

    history_val = 0.0
    for ep in range(epochs):
        model.train()
        order = torch.randperm(x_tr.size(0))
        for start in range(0, x_tr.size(0), 64):
            idx = order[start:start + 64]
            logits = model(x_tr[idx])
            loss = (F.cross_entropy(logits, y_tr[idx], weight=class_w, reduction="none")
                    * w_tr[idx]).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            history_val = acc(model(x_val), y_val)
            train_a = acc(model(x_tr), y_tr)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "code_nfet_head",
        "version": 1,
        "n_features": N_FEATURES,
        "n_controls": N_CONTROLS,
        "labels": CONTROL_LABELS,
        "state_dict": model.state_dict(),
        "train_acc": train_a,
        "val_acc": history_val,
        "n_rows": n,
        "class_counts": [int(c) for c in counts.tolist()],
        "feature_names": [
            "entropy", "drift", "gate", "regime",
            "thrash_norm", "green_frac", "fail_frac", "contract_failed", "exit_ok",
        ],
    }
    torch.save(payload, out)
    return TrainResult(
        path=out, train_acc=train_a, val_acc=history_val, n_rows=n,
        class_counts=[int(c) for c in counts.tolist()], epochs=epochs,
    )


def load_coding_head(path: Path) -> Optional[Tuple[CodingControlHead, Dict[str, Any]]]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        ckpt = torch.load(p, map_location="cpu", weights_only=False)
    except TypeError:
        ckpt = torch.load(p, map_location="cpu")
    if not isinstance(ckpt, dict) or ckpt.get("kind") != "code_nfet_head":
        return None
    model = CodingControlHead(n_in=int(ckpt.get("n_features") or N_FEATURES))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, ckpt


def predict_control(
    model: CodingControlHead,
    features: Sequence[float],
    *,
    min_confidence: float = 0.45,
) -> Optional[Tuple[int, List[float]]]:
    """Return (control_id, probs) if confident, else None."""
    with torch.no_grad():
        x = torch.tensor([list(features)], dtype=torch.float32)
        logits = model(x)[0]
        probs = torch.softmax(logits, dim=-1).tolist()
    best = max(range(len(probs)), key=probs.__getitem__)
    if probs[best] < min_confidence:
        return None
    return best, probs
