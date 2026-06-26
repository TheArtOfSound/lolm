# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Does any CHEAP local graft signal recover the TRUE (interventional) causal K?

Computes K_int (do-perturbation downstream divergence) as ground truth, then asks whether
the local signals the implemented K-channel could use (entropy/drift/gate/regime/Phi-K)
predict it. If one does -> the cheap K-channel is justified (F4 can survive with it). If
none does -> NFET's causal channel genuinely requires the intervention. Honest either way.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch

from lolm.hf_backbone import FrozenHFBackbone
from lolm.nfet_graft import LOLMNFETGraft
from lolm.nfet_intervene import interventional_k
from lolm.nfet_measure import _frame, spearman
from local_ui.claude_reasoner import telemetry_traces_from_text

PROMPTS = [
    "What is 17 times 23? Explain briefly.",
    "Who is the president of France?",
    "If all bloops are razzies and all razzies are lazzies, are all bloops lazzies?",
    "Summarize why the sky is blue.",
    "Continue the sequence: 2, 4, 8, 16, ...",
    "Give three reasons local AI matters.",
    "What happens if you divide by zero?",
    "Translate 'good morning' into French.",
]
H = 4


def main() -> None:
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"loading on {dev} ...", flush=True)
    bb = FrozenHFBackbone.from_registry("qwen3_0_6b_smoke", "configs/hf_models.yaml",
                                        freeze=True).to(dev)
    g = LOLMNFETGraft(d_model=bb.hidden_size, latent_backend="gru_debug")  # type: ignore[arg-type]
    ck = Path("runs/nfet_controller/bootstrap_qwen06b.pt")
    if ck.exists():
        g.load_state_dict(torch.load(ck, map_location="cpu")["graft"])
    g.to(dev).eval()

    sig = {"entropy": [], "drift": [], "gate": [], "regime": []}
    kint, downstream = [], []
    for pr in PROMPTS:
        frames = telemetry_traces_from_text(bb, g, pr)
        rows = [_frame(f) for f in frames]
        ki = interventional_k(bb, pr, horizon=H, draws=3)
        if not ki:
            continue
        for i, kval in ki.items():
            if i + H >= len(rows) or i >= len(rows):
                continue
            e, d, ga, r = rows[i]
            sig["entropy"].append(e); sig["drift"].append(d)
            sig["gate"].append(ga); sig["regime"].append(r)
            kint.append(kval)
            downstream.append(sum(x[1] for x in rows[i + 1:i + 1 + H]) / H)
        print(f"  {pr[:34]:34} positions={len(ki)}", flush=True)

    n = len(kint)
    report = {
        "events": n,
        "K_int_vs_downstream_drift": round(spearman(kint, downstream), 3),
        "local_signal_recovers_K_int": {
            name: round(spearman(vals, kint), 3) for name, vals in sig.items()
        },
    }
    best = max(report["local_signal_recovers_K_int"].items(), key=lambda kv: kv[1])
    report["best_local_predictor_of_K_int"] = {"signal": best[0], "rho": best[1]}
    report["F4_verdict"] = (
        f"SURVIVES — '{best[0]}' recovers the true causal K (rho={best[1]})"
        if best[1] > 0.2 else
        "FIRES — no cheap local signal recovers the true causal K; the intervention is required")
    print("\n" + json.dumps(report, indent=2))
    Path("runs/nfet_intervene_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
