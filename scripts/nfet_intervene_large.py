# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Large-n interventional test — settle whether the local K-channel recovers the TRUE
causal K_int, with a bootstrap CI, and preview a LEARNED K-head (linear combination of
local signals, cross-validated). Decides: real-but-weak, or noise.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from lolm.hf_backbone import FrozenHFBackbone
from lolm.nfet_graft import LOLMNFETGraft
from lolm.nfet_intervene import interventional_k
from lolm.nfet_measure import _frame, spearman
from local_ui.claude_reasoner import telemetry_traces_from_text

H = 4
PROMPTS = [
    "What is 17 times 23? Explain your steps briefly.",
    "Who is the current president of France and when were they elected?",
    "If all bloops are razzies and all razzies are lazzies, are all bloops lazzies? Explain.",
    "Summarize in two sentences why the sky appears blue during the day.",
    "Continue the sequence and state the rule: 2, 4, 8, 16, 32, ...",
    "Give three concrete reasons local AI matters for ordinary people.",
    "What happens, mathematically, if you try to divide a number by zero?",
    "Translate 'good morning, how are you' into French and then into Japanese.",
    "Explain the difference between weather and climate in plain language.",
    "A farmer has 17 sheep and all but 9 run away. How many are left? Explain.",
    "What is the capital of Australia, and why is it not Sydney?",
    "Describe how a bill becomes law in three short steps.",
    "Is the statement 'this sentence is false' true or false? Reason carefully.",
    "List the planets of the solar system in order from the sun.",
    "Why does ice float on water? Give the physical reason.",
    "What is photosynthesis, in one paragraph?",
    "Compute the area of a circle with radius 5. Show the formula.",
    "Name three causes of the First World War.",
    "Explain recursion to a beginner using a simple example.",
    "What is the boiling point of water at sea level in Celsius and Fahrenheit?",
    "Why do we have seasons? Explain the role of Earth's tilt.",
    "Give a short definition of inflation in economics.",
    "What is the difference between a virus and a bacterium?",
    "If a train leaves at 3pm going 60mph, how far in 2.5 hours?",
    "Explain what a black hole is without using equations.",
    "What are the primary colors of light, and what do they combine to make?",
    "Summarize the plot of Romeo and Juliet in three sentences.",
    "How does a vaccine train the immune system? Keep it brief.",
    "What is the Pythagorean theorem and when do you use it?",
    "Why is biodiversity important for ecosystems?",
    "Define entropy in thermodynamics in one sentence.",
    "What is the tallest mountain on Earth and how tall is it?",
    "Explain the water cycle in four steps.",
    "What does GDP measure and what are its limits?",
    "Give the chemical formula for table salt and explain it.",
    "Why can't you hear sound in space?",
    "What is machine learning, in two sentences, for a 12-year-old?",
    "List three renewable energy sources and one drawback of each.",
    "What is the difference between mass and weight?",
    "Explain why prime numbers matter in cryptography, briefly.",
]


def main() -> None:
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"loading on {dev} ... ({len(PROMPTS)} prompts)", flush=True)
    bb = FrozenHFBackbone.from_registry("qwen3_0_6b_smoke", "configs/hf_models.yaml",
                                        freeze=True).to(dev)
    g = LOLMNFETGraft(d_model=bb.hidden_size, latent_backend="gru_debug")  # type: ignore[arg-type]
    ck = Path("runs/nfet_controller/bootstrap_qwen06b.pt")
    if ck.exists():
        g.load_state_dict(torch.load(ck, map_location="cpu")["graft"])
    g.to(dev).eval()

    cols = {"entropy": [], "drift": [], "gate": [], "regime": []}
    kint, down = [], []
    for n_done, pr in enumerate(PROMPTS, 1):
        frames = telemetry_traces_from_text(bb, g, pr)
        rows = [_frame(f) for f in frames]
        ki = interventional_k(bb, pr, horizon=H, draws=2)
        for i, kv in ki.items():
            if i >= len(rows) or i + H >= len(rows):
                continue
            e, d, ga, r = rows[i]
            cols["entropy"].append(e); cols["drift"].append(d)
            cols["gate"].append(ga); cols["regime"].append(r)
            kint.append(kv)
            down.append(sum(x[1] for x in rows[i + 1:i + 1 + H]) / H)
        if n_done % 10 == 0:
            print(f"  {n_done}/{len(PROMPTS)} prompts, {len(kint)} events", flush=True)

    y = np.array(kint)
    n = len(y)

    def boot_ci(a, b, B=2000):
        rng = np.random.default_rng(0)
        rs = []
        a = np.array(a); b = np.array(b)
        for _ in range(B):
            idx = rng.integers(0, n, n)
            rs.append(spearman(a[idx].tolist(), b[idx].tolist()))
        lo, hi = np.percentile(rs, [2.5, 97.5])
        return float(lo), float(hi)

    uni = {}
    for name, v in cols.items():
        rho = spearman(v, kint)
        lo, hi = boot_ci(v, kint)
        uni[name] = {"rho": round(rho, 3), "ci95": [round(lo, 3), round(hi, 3)],
                     "excludes_0": bool(lo > 0 or hi < 0)}

    # learned K-head preview: 5-fold CV linear fit of K_int on standardized local signals
    X = np.column_stack([np.array(cols[c]) for c in cols])
    X = (X - X.mean(0)) / (X.std(0) + 1e-9)
    X = np.column_stack([X, np.ones(n)])
    rng = np.random.default_rng(1)
    order = rng.permutation(n)
    folds = np.array_split(order, 5)
    preds = np.zeros(n)
    for f in range(5):
        te = folds[f]; tr = np.concatenate([folds[j] for j in range(5) if j != f])
        w, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        preds[te] = X[te] @ w
    cv_rho = spearman(preds.tolist(), kint)
    lo_m, hi_m = boot_ci(preds.tolist(), kint)

    report = {
        "events": n,
        "K_int_vs_downstream_drift": round(spearman(down, kint), 3),
        "single_signal_recovers_K_int": uni,
        "learned_K_head_cv": {"rho": round(cv_rho, 3), "ci95": [round(lo_m, 3), round(hi_m, 3)],
                              "excludes_0": bool(lo_m > 0)},
    }
    best = max(uni.items(), key=lambda kv: kv[1]["rho"])
    real = best[1]["excludes_0"] and best[1]["rho"] > 0.15
    learned_better = cv_rho > best[1]["rho"] + 0.03 and hi_m > 0 and lo_m > 0
    report["verdict"] = (
        ("REAL-BUT-WEAK: causal channel recoverable" if real else "NOISE: no single signal robustly recovers K_int")
        + (f"; LEARNED head improves it to rho={round(cv_rho,3)} (justifies a K-head)" if learned_better else "")
    )
    print("\n" + json.dumps(report, indent=2))
    Path("runs/nfet_intervene_large_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
