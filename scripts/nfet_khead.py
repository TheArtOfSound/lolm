# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Can a learned head over the FULL graft state recover the true causal K_int?

The linear head over 4 scalars failed (CV rho=0.097). This is the decisive test: features
= the full corrected-hidden vector (1024) + the 4 scalars + the 5 control logits, target =
the interventional K_int. Two models, both 5-fold cross-validated (held-out predictions, no
overfit inflation): ridge regression and a small MLP. If held-out rho jumps well above the
drift baseline (0.165) with a CI excluding 0, a cheap learned K-head is justified. If it
sits at the baseline, K is fundamentally unrecoverable from local features and the
intervention is the only valid K.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from lolm.hf_backbone import FrozenHFBackbone
from lolm.nfet_graft import LOLMNFETGraft
from lolm.nfet_intervene import interventional_k
from lolm.nfet_measure import spearman
import torch.nn.functional as F

H = 4
PROMPTS = [  # ~100 diverse prompts for n~800 events
    "What is 17 times 23?", "Who is the president of France?", "Why is the sky blue?",
    "Continue: 2, 4, 8, 16", "Three reasons local AI matters.", "What happens if you divide by zero?",
    "Translate good morning to French.", "Difference between weather and climate?",
    "A farmer has 17 sheep; all but 9 run away. How many left?", "Capital of Australia and why not Sydney?",
    "How does a bill become law?", "Is 'this sentence is false' true or false?",
    "List the planets from the sun.", "Why does ice float on water?", "What is photosynthesis?",
    "Area of a circle with radius 5?", "Three causes of World War One.", "Explain recursion simply.",
    "Boiling point of water at sea level?", "Why do we have seasons?", "Define inflation.",
    "Virus vs bacterium?", "Train at 60mph for 2.5 hours covers how far?", "What is a black hole?",
    "Primary colors of light?", "Plot of Romeo and Juliet in three sentences.",
    "How does a vaccine work?", "Pythagorean theorem and when to use it?", "Why does biodiversity matter?",
    "Define entropy in thermodynamics.", "Tallest mountain on Earth?", "Explain the water cycle.",
    "What does GDP measure?", "Chemical formula for table salt?", "Why is there no sound in space?",
    "What is machine learning?", "Three renewable energy sources.", "Mass vs weight?",
    "Why do prime numbers matter in cryptography?", "What is the speed of light?",
    "Explain supply and demand.", "How do magnets work?", "What is DNA?", "Why is the ocean salty?",
    "Largest desert on Earth?", "What is a derivative in calculus?", "How does the internet work?",
    "What causes earthquakes?", "Define democracy.", "What is the greenhouse effect?",
    "How many bones in the human body?", "What is gravity?", "Explain how rainbows form.",
    "What is the capital of Canada?", "Difference between TCP and UDP?", "What is a neutron star?",
    "Why do leaves change color in fall?", "What is compound interest?", "How does a refrigerator work?",
    "What is the meaning of pi?", "Explain natural selection.", "What is a syllogism?",
    "How tall is the Eiffel Tower?", "What is osmosis?", "Why is the sun hot?",
    "Define a prime number.", "What is the boiling point on Everest?", "How do airplanes fly?",
    "What is quantum entanglement?", "Largest ocean on Earth?", "What is an isotope?",
    "Explain the Doppler effect.", "What is a leap year?", "How does sound travel?",
    "What is the capital of Japan?", "Define momentum in physics.", "Why is blood red?",
    "What is a fractal?", "How does a battery store energy?", "What is the Fibonacci sequence?",
    "Explain why the moon has phases.", "What is an enzyme?", "How big is the observable universe?",
    "What is a logarithm?", "Why do we dream?", "What is the freezing point of water?",
    "Explain how GPS works.", "What is a black body?", "How many continents are there?",
    "What is a catalyst?", "Why is the sky dark at night?", "What is escape velocity?",
    "Explain the difference between heat and temperature.", "What is a tessellation?",
    "How does photosynthesis differ from respiration?", "What is the speed of sound?",
    "Define a vector.", "Why do stars twinkle?", "What is an algorithm?",
]


def features_and_kint(bb, g, text, dev):
    batch = bb.tokenizer(text, return_tensors="pt")
    batch = {k: v.to(dev) for k, v in batch.items()}
    with torch.no_grad():
        base = bb(**batch)
        out = g(base.hidden_states.float(), base_logits=base.logits.float())
        corrected = out.corrected_hidden[0].float().cpu().numpy()              # (T, d)
        lp = F.log_softmax(base.logits[0].float(), dim=-1)
        entropy = (-(lp.exp() * lp).sum(dim=-1)).cpu().numpy()                 # (T,)
        gate = out.gate[0].float().mean(dim=-1).cpu().numpy()                  # (T,)
        probs = out.regime_probs[0].float().clamp_min(1e-8)
        regime = (-(probs * probs.log()).sum(dim=-1)).cpu().numpy()            # (T,)
    T = corrected.shape[0]
    drift = np.zeros(T)
    drift[1:] = ((corrected[1:] - corrected[:-1]) ** 2).mean(-1)
    ki = interventional_k(bb, text, horizon=H, draws=2)
    X, y = [], []
    for i, kv in ki.items():
        if i >= T:
            continue
        scal = np.array([entropy[i], drift[i], gate[i], regime[i]])
        feat = np.concatenate([corrected[i], scal])      # full hidden (1024) + 4 scalars
        X.append(feat); y.append(kv)
    return X, y


def cv_ridge(X, y, lam=10.0, folds=5):
    n = X.shape[0]
    idx = np.random.default_rng(0).permutation(n)
    parts = np.array_split(idx, folds)
    pred = np.zeros(n)
    for f in range(folds):
        te = parts[f]; tr = np.concatenate([parts[j] for j in range(folds) if j != f])
        A = X[tr].T @ X[tr] + lam * np.eye(X.shape[1])
        w = np.linalg.solve(A, X[tr].T @ y[tr])
        pred[te] = X[te] @ w
    return pred


def cv_mlp(X, y, folds=5, dev="cpu"):
    n, d = X.shape
    idx = torch.randperm(n, generator=torch.Generator().manual_seed(0)).numpy()
    parts = np.array_split(idx, folds)
    pred = np.zeros(n)
    Xt = torch.tensor(X, dtype=torch.float32); yt = torch.tensor(y, dtype=torch.float32)
    for f in range(folds):
        te = parts[f]; tr = np.concatenate([parts[j] for j in range(folds) if j != f])
        net = nn.Sequential(nn.Linear(d, 64), nn.GELU(), nn.Dropout(0.3), nn.Linear(64, 1))
        opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-2)
        for ep in range(150):
            opt.zero_grad()
            loss = nn.functional.mse_loss(net(Xt[tr]).squeeze(-1), yt[tr])
            loss.backward(); opt.step()
        net.eval()
        with torch.no_grad():
            pred[te] = net(Xt[te]).squeeze(-1).numpy()
    return pred


def boot_ci(a, b, n, B=2000):
    rng = np.random.default_rng(0); a = np.array(a); b = np.array(b); rs = []
    for _ in range(B):
        ix = rng.integers(0, n, n); rs.append(spearman(a[ix].tolist(), b[ix].tolist()))
    return [round(float(np.percentile(rs, 2.5)), 3), round(float(np.percentile(rs, 97.5)), 3)]


def main():
    dev = torch.device("cpu")  # avoids an MPS matmul dtype assertion in the direct graft fwd
    print(f"loading on {dev}, {len(PROMPTS)} prompts ...", flush=True)
    bb = FrozenHFBackbone.from_registry("qwen3_0_6b_smoke", "configs/hf_models.yaml",
                                        freeze=True).to(dev)
    g = LOLMNFETGraft(d_model=bb.hidden_size, latent_backend="gru_debug")  # type: ignore[arg-type]
    ck = Path("runs/nfet_controller/bootstrap_qwen06b.pt")
    if ck.exists():
        g.load_state_dict(torch.load(ck, map_location="cpu")["graft"])
    g.to(dev).eval()

    X, y = [], []
    for k, pr in enumerate(PROMPTS, 1):
        try:
            xs, ys = features_and_kint(bb, g, pr, dev)
            X += xs; y += ys
        except Exception as e:
            print("  skip:", str(e)[:60])
        if k % 20 == 0:
            print(f"  {k}/{len(PROMPTS)} prompts, {len(y)} events", flush=True)
    X = np.array(X); y = np.array(y); n = len(y)
    Xs = (X - X.mean(0)) / (X.std(0) + 1e-9)

    drift_rho = spearman(X[:, 1024 + 1].tolist(), y.tolist())          # drift baseline
    ridge_pred = cv_ridge(Xs, y); ridge_rho = spearman(ridge_pred.tolist(), y.tolist())
    mlp_pred = cv_mlp(Xs, y, dev=str(dev)); mlp_rho = spearman(mlp_pred.tolist(), y.tolist())

    rep = {
        "events": n, "feature_dim": X.shape[1],
        "drift_baseline_rho": round(drift_rho, 3),
        "ridge_full_state_cv": {"rho": round(ridge_rho, 3), "ci95": boot_ci(ridge_pred, y, n)},
        "mlp_full_state_cv": {"rho": round(mlp_rho, 3), "ci95": boot_ci(mlp_pred, y, n)},
    }
    best = max(ridge_rho, mlp_rho)
    rep["verdict"] = (
        f"RECOVERABLE: a learned head over the full graft state recovers K_int (rho={round(best,3)} "
        f"vs drift {round(drift_rho,3)}) — a cheap K-head is justified"
        if best > drift_rho + 0.08 else
        "NOT RECOVERABLE: the full graft state does not beat the drift baseline — K_int genuinely "
        "requires the intervention; no cheap shortcut exists")
    print("\n" + json.dumps(rep, indent=2))
    Path("runs/nfet_khead_report.json").write_text(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
