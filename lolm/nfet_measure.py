# Copyright (c) 2026 Qira LLC. All rights reserved.
"""NFET measures as estimators over graft telemetry — and a Neyman-Pearson derivation
of the event threshold theta that removes it as a free parameter.

This is the bridge between the NFET formalization and the running system. Each token
transition produced by the graft carries telemetry (logit entropy, hidden drift, gate
mean, regime entropy); here those become sample estimators of the event-coherence
channels I, B, P, K, N and the composite Phi. theta is NOT a knob: it is derived as the
(1 - alpha) quantile of Phi under the NULL (temporally shuffled = noise) distribution, so
that the rejection region {Phi >= theta} has false-event rate alpha by construction
(Neyman-Pearson: fix the size of the test under H0, here H0 = "this transition is noise").

Honest scope (matches sec. 11.6 / sec. 14 of the spec): the channel definitions below are
PROXIES estimated from graft outputs. K is estimated from the token's LOCAL signal only
(not from the future), so that "does K track real downstream influence?" (falsifier F4) is
a non-circular test against a separately-measured downstream quantity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

# default exchange rates (sec. 13: model-relative free parameters, surfaced explicitly)
WEIGHTS = (1.0, 0.6, 0.4, 1.0, 1.0)   # alpha I, beta B, gamma P, delta K, lambda N


def squash(x: float) -> float:
    """ΔH-style nonneg quantity -> [0,1)."""
    return 1.0 - math.exp(-max(x, 0.0))


@dataclass
class Channels:
    I: float   # uncertainty reduction (ΔH)
    B: float   # boundary / constraint-surface change (Δgate)
    P: float   # persistence of the post-transition configuration
    K: float   # LOCAL estimate of downstream causal consequence
    N: float   # noise penalty (filled after the null is built)


def phi(ch: Channels, w: Sequence[float] = WEIGHTS) -> float:
    return w[0] * ch.I + w[1] * ch.B + w[2] * ch.P + w[3] * ch.K - w[4] * ch.N


def _frame(f: Dict) -> Tuple[float, float, float, float]:
    """(entropy, drift, gate, regime) from a telemetry frame, tolerating key variants."""
    e = float(f.get("logit_entropy", f.get("graft_entropy", 0.0)) or 0.0)
    d = float(f.get("hidden_drift", 0.0) or 0.0)
    g = float(f.get("gate_mean", 0.0) or 0.0)
    r = float(f.get("regime_entropy", 0.0) or 0.0)
    return e, d, g, r


def channels_for_sequence(frames: Sequence[Dict], horizon: int = 4
                          ) -> Tuple[List[Channels], List[float]]:
    """Per-token channels (no N yet) + a SEPARATELY measured downstream-influence vector
    (mean hidden drift over the next `horizon` tokens) used only as ground truth for the
    falsification tests — never fed into K."""
    rows = [_frame(f) for f in frames]
    n = len(rows)
    chans: List[Channels] = []
    downstream: List[float] = []
    drift_scale = (sum(r[1] for r in rows) / n + 1e-9) if n else 1.0
    gate_scale = (sum(abs(rows[i][2] - rows[i - 1][2]) for i in range(1, n)) / max(n - 1, 1)) + 1e-9
    # only emit tokens that HAVE a full downstream horizon — "downstream influence" is
    # undefined for end-of-sequence tokens, and the old d1 fallback injected noise.
    for i in range(1, max(1, n - horizon)):
        e0, d0, g0, r0 = rows[i - 1]
        e1, d1, g1, r1 = rows[i]
        I = squash(max(e0 - e1, 0.0))                       # reduced uncertainty
        B = squash(abs(g1 - g0) / gate_scale)               # constraint-surface jump
        fut = rows[i + 1:i + 1 + horizon]                   # always exactly `horizon`
        stab = sum(x[1] for x in fut) / horizon
        P = math.exp(-stab / (drift_scale + 1e-9))
        # K = LOCAL estimate of downstream consequence. F4 REJECTED the original (regime
        # dispersion, rho=-0.13). Hidden drift is the BEST available local predictor
        # (rho=+0.33 in long contexts) yet F4 STILL FIRES pooled (rho~0): on this graft the
        # causal-consequence channel is NOT robustly supported by any single local signal.
        # A faithful K needs do-interventions (sec.14) we cannot run offline. Kept as drift
        # (least-bad estimator); F4 is reported as FIRING — the honest finding, not tuned away.
        K = squash(d1 / (drift_scale + 1e-9))
        chans.append(Channels(I=I, B=B, P=P, K=K, N=0.0))
        downstream.append(stab)                              # ground-truth downstream change
    return chans, downstream


def _null_frames(frames: Sequence[Dict], seed: int) -> List[Dict]:
    """H0 (noise): destroy temporal structure by a deterministic permutation."""
    import random
    idx = list(range(len(frames)))
    random.Random(seed).shuffle(idx)
    return [frames[i] for i in idx]


def null_phi(frames: Sequence[Dict], w: Sequence[float] = WEIGHTS,
             shuffles: int = 40, horizon: int = 4) -> List[float]:
    """Phi values under the null (shuffled) distribution — the H0 sample."""
    out: List[float] = []
    for s in range(shuffles):
        nf = _null_frames(frames, seed=1000 + s)
        chans, _ = channels_for_sequence(nf, horizon=horizon)
        # noise penalty N is ~1 under the null by construction (no structure to exceed it);
        # here Phi excludes N so theta is set on the structural channels vs their own null.
        out.extend(phi(c, w) for c in chans)
    return out


def derive_theta(null_phi_samples: Sequence[float], alpha: float = 0.05) -> float:
    """Neyman-Pearson: theta = (1-alpha) quantile of Phi under H0, so the rejection
    region {Phi >= theta} has size (false-event rate) alpha. Removes theta as a free
    parameter, replacing it with the interpretable alpha."""
    if not null_phi_samples:
        return float("inf")
    xs = sorted(null_phi_samples)
    k = min(len(xs) - 1, max(0, int(math.ceil((1.0 - alpha) * len(xs))) - 1))
    return xs[k]


def false_event_rate(null_phi_samples: Sequence[float], theta: float) -> float:
    if not null_phi_samples:
        return 0.0
    return sum(1 for x in null_phi_samples if x >= theta) / len(null_phi_samples)


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Rank correlation, no scipy."""
    n = len(a)
    if n < 3:
        return 0.0
    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        rk = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    va = math.sqrt(sum((ra[i] - ma) ** 2 for i in range(n)))
    vb = math.sqrt(sum((rb[i] - mb) ** 2 for i in range(n)))
    return cov / (va * vb) if va > 0 and vb > 0 else 0.0


def eta_squared(values: Sequence[float], bins: Sequence[int]) -> float:
    """Fraction of variance in `values` explained by the discrete grouping `bins`
    (one-way ANOVA eta^2). Used for F1: does Phi-bin membership separate downstream
    behavior? ~0 => Phi under-specifies the transition (F1 fires)."""
    n = len(values)
    if n < 3:
        return 0.0
    grand = sum(values) / n
    ss_tot = sum((v - grand) ** 2 for v in values) + 1e-12
    groups: Dict[int, List[float]] = {}
    for v, b in zip(values, bins):
        groups.setdefault(b, []).append(v)
    ss_between = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups.values())
    return ss_between / ss_tot
