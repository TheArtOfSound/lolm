# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Run the NFET measures + the Neyman-Pearson theta derivation + the falsifiers F1/F4
on REAL graft telemetry. This is where the theory can fail against data.

  - theta derived so the rejection region {Phi>=theta} has false-event rate alpha.
  - F4: does the K-channel (estimated from a token's LOCAL signal) predict the SEPARATELY
        measured downstream reconfiguration? corr<=0 => F4 fires (K mis-specified).
  - F1: does Phi-bin membership separate downstream behavior (eta^2)? ~0 => Phi
        under-specifies the transition => F1 fires.

  python scripts/nfet_falsify.py
"""
from __future__ import annotations

import json
from pathlib import Path

import torch

from lolm.hf_backbone import FrozenHFBackbone
from lolm.nfet_graft import LOLMNFETGraft
from local_ui.claude_reasoner import telemetry_traces_from_text
from lolm.nfet_measure import (channels_for_sequence, derive_theta, eta_squared,
                               false_event_rate, null_phi, phi, spearman)

PROMPTS = [
    "What is 17 times 23? Explain briefly.",
    "Who is the president of France?",
    "Write a haiku about the ocean.",
    "If all bloops are razzies and all razzies are lazzies, are all bloops lazzies?",
    "This statement is false. Is it true or false?",
    "Summarize why the sky is blue.",
    "What is the capital of a country that does not exist?",
    "Continue the sequence: 2, 4, 8, 16, ...",
    "Give three reasons local AI matters.",
    "Translate 'good morning' into French and Japanese.",
    "What happens if you divide by zero?",
    "Describe the smell of the color seven.",
]
ALPHA = 0.05


def main() -> None:
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"loading graft on {dev} ...", flush=True)
    backbone = FrozenHFBackbone.from_registry("qwen3_0_6b_smoke", "configs/hf_models.yaml",
                                              freeze=True).to(dev)
    graft = LOLMNFETGraft(d_model=backbone.hidden_size, latent_backend="gru_debug")  # type: ignore[arg-type]
    ck = Path("runs/nfet_controller/bootstrap_qwen06b.pt")
    if ck.exists():
        graft.load_state_dict(torch.load(ck, map_location="cpu")["graft"])
    graft.to(dev).eval()

    all_phi, all_down, all_K, all_frames = [], [], [], []
    for pr in PROMPTS:
        frames = telemetry_traces_from_text(backbone, graft, pr)
        if len(frames) < 6:
            continue
        all_frames.extend(frames)
        chans, down = channels_for_sequence(frames, horizon=4)
        for c, d in zip(chans, down):
            all_phi.append(phi(c))
            all_down.append(d)            # separately-measured downstream reconfiguration
            all_K.append(c.K)             # local estimate (regime dispersion)

    n = len(all_phi)
    print(f"collected {n} token-transition events across {len(PROMPTS)} prompts.\n", flush=True)

    # (a) theta via Neyman-Pearson on the null
    null = null_phi(all_frames, shuffles=30)
    theta = derive_theta(null, ALPHA)
    fer = false_event_rate(null, theta)
    n_events = sum(1 for x in all_phi if x >= theta)

    # (F4) does K predict the actual downstream reconfiguration?
    rho_K = spearman(all_K, all_down)

    # (F1) does Phi separate downstream behavior?
    xs = sorted(all_phi)
    q = [xs[int(0.25 * n)], xs[int(0.5 * n)], xs[int(0.75 * n)]]
    bins = [sum(1 for t in q if p >= t) for p in all_phi]    # quartile bin 0..3
    eta = eta_squared(all_down, bins)
    # also: does Phi itself correlate with downstream (a stronger positive check)?
    rho_phi = spearman(all_phi, all_down)

    report = {
        "events": n,
        "alpha_target_false_event_rate": ALPHA,
        "theta_derived": round(theta, 4),
        "false_event_rate_achieved": round(fer, 4),
        "events_detected_at_theta": n_events,
        "F4_K_tracks_downstream": {
            "spearman_rho": round(rho_K, 3),
            "verdict": "SURVIVES (K tracks downstream)" if rho_K > 0.1
                       else "FIRES (K does not predict downstream → K mis-specified)",
        },
        "F1_phi_separates_downstream": {
            "eta_squared": round(eta, 3),
            "phi_vs_downstream_spearman": round(rho_phi, 3),
            "verdict": "SURVIVES (Phi separates behavior)" if eta > 0.02
                       else "FIRES (Phi does not separate downstream → under-specified)",
        },
    }
    print(json.dumps(report, indent=2))
    Path("runs/nfet_falsify_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
