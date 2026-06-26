# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Autonomous local evolution — LOLM changes its OWN weights, behind a proof gate.

This is the honest core of "trains globally to become locally itself": a cycle that
genuinely updates the NFET controller's parameters from fresh data (synthetic scenarios
+ LOLM's own logged experience), then PROMOTES the new weights only if a fixed held-out
eval proves they are at least as good as the incumbent. If a candidate would regress, it
is rejected and the current weights are kept — so the model only ever moves forward.
Every cycle writes a receipt: weights_changed, accuracy before/after, the decision.

What evolves here is the controller (the uncertainty-control brain) — real weights, on
the Apple GPU, today. The same gated loop is the slot the full-model LoRA fine-tune drops
into next (heavier; needs mlx_lm/peft). Nothing here fakes learning: if a cycle promotes,
weights_changed is true and the checkpoint hash changes; if it rejects, it says so.

Physics, stated honestly: this runs while the machine is AWAKE. Left running (Mac kept
awake), it evolves for days unattended. It cannot compute while powered off.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from lolm.nfet_graft import LOLMNFETGraft
from lolm.nfet_controller_train import (
    build_dataset, save_controller_checkpoint, synth_scenarios, train_control_head,
)

D_MODEL = 1024                  # Qwen3-0.6B graft hidden size
LATENT_BACKEND = "gru_debug"
EVAL_N = 64                     # fixed held-out eval set size
EVAL_SEED = 4242                # FIXED so current vs candidate is apples-to-apples


def _device(name: str = "") -> torch.device:
    if name:
        return torch.device(name)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _fresh_graft(device: torch.device) -> LOLMNFETGraft:
    return LOLMNFETGraft(d_model=D_MODEL, latent_backend=LATENT_BACKEND).to(device)  # type: ignore[arg-type]


def _load_graft(ckpt: Path, device: torch.device) -> Optional[LOLMNFETGraft]:
    if not ckpt.exists():
        return None
    g = _fresh_graft(device)
    state = torch.load(ckpt, map_location="cpu")
    g.load_state_dict(state["graft"])
    return g.to(device)


def _eval_acc(graft: LOLMNFETGraft, device: torch.device,
              n: int = EVAL_N, seed: int = EVAL_SEED) -> float:
    """Score a graft's control head on a FIXED held-out synthetic set (apples-to-apples
    across cycles) — the metric the proof gate trusts."""
    ds = build_dataset(synth_scenarios(n, seed=seed), d_model=D_MODEL,
                       continue_keep_ratio=0.25, seed=seed)
    head = graft.nfet.head.to(device).eval()
    with torch.no_grad():
        logits = head(ds.features.to(device))
        return float((logits.argmax(dim=-1) == ds.labels.to(device)).float().mean())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else ""


@dataclass
class EvolveState:
    cycle: int = 0
    promoted: int = 0
    rejected: int = 0
    best_val_acc: float = 0.0
    current_sha: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "EvolveState":
        if path.exists():
            try:
                return cls(**json.loads(path.read_text()))
            except Exception:
                pass
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2))


def run_cycle(root: Path, *, device: Optional[str] = None, synth_n: int = 120,
              epochs: int = 6, tolerance: float = 0.0,
              real_log: Optional[Path] = None) -> Dict[str, Any]:
    """One gated evolution step. Returns the receipt; mutates the durable state +
    promotes the candidate checkpoint iff it does not regress on the fixed eval."""
    root = Path(root)
    dev = _device(device or "")
    state_path = root / "state.json"
    current = root / "current.pt"
    state = EvolveState.load(state_path)
    cyc = state.cycle + 1
    t0 = time.time()

    # incumbent (or a fresh untrained head if this is the very first cycle)
    cur_graft = _load_graft(current, dev) or _fresh_graft(dev)
    baseline = _eval_acc(cur_graft, dev)

    # candidate: continue training FROM the incumbent on FRESH data (new seed each cycle,
    # plus LOLM's own logged experience if available) — this is the real weight update.
    cand = _load_graft(current, dev) or _fresh_graft(dev)
    seqs = synth_scenarios(synth_n, seed=1000 + cyc)
    real_rows = 0
    if real_log and Path(real_log).exists():
        try:
            from lolm.nfet_controller_train import load_log_sequences
            log_seqs = load_log_sequences(Path(real_log))
            real_rows = len(log_seqs)
            seqs = list(seqs) + list(log_seqs)
        except Exception:
            pass
    ds = build_dataset(seqs, d_model=D_MODEL, continue_keep_ratio=0.25, seed=1000 + cyc)
    metrics = train_control_head(cand, ds, epochs=epochs, zero_hidden_weights=True,
                                 device=dev, seed=1000 + cyc)
    cand_acc = _eval_acc(cand, dev)

    # PROOF GATE: promote only if the candidate does not regress on the fixed eval.
    promote = cand_acc >= (baseline - tolerance)
    weights_changed = False
    if promote:
        save_controller_checkpoint(cand, current, metrics)
        state.promoted += 1
        state.best_val_acc = max(state.best_val_acc, cand_acc)
        weights_changed = True
        decision = "promoted"
    else:
        state.rejected += 1
        decision = "rejected (would regress) — kept current weights"

    receipt = {
        "cycle": cyc,
        "ts": int(t0),
        "decision": decision,
        "weights_changed": weights_changed,             # never lies
        "val_acc_before": round(baseline, 4),
        "val_acc_after": round(cand_acc if promote else baseline, 4),
        "candidate_val_acc": round(cand_acc, 4),
        "gain": round((cand_acc - baseline) if promote else 0.0, 4),
        "best_val_acc": round(state.best_val_acc, 4),
        "train_rows": int(metrics.get("train_rows", 0)),
        "synth_sequences": synth_n,
        "experience_sequences": real_rows,
        "epochs": epochs,
        "device": str(dev),
        "checkpoint_sha": _sha(current),
        "seconds": round(time.time() - t0, 1),
        "what_evolved": "nfet_controller_head",
    }
    state.cycle = cyc
    state.current_sha = receipt["checkpoint_sha"]
    state.history = (state.history + [receipt])[-50:]
    state.save(state_path)
    with (root / "receipts.jsonl").open("a") as fh:
        fh.write(json.dumps(receipt) + "\n")
    return receipt
