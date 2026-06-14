# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Calibration — turn measured uncertainty into a real probability of correctness.

The graft streams per-token telemetry (entropy / drift / gate / regime). On its
own that is a signal, not a probability. This module closes the gap that makes
uncertainty-gated autonomy *sound* instead of vibes:

    raw uncertainty  U  --(isotonic calibration on logged outcomes)-->  P(correct | U)

and, for autonomy with a guarantee:

    selective_threshold(U, outcomes, target_risk)  ->  the largest uncertainty
    we may accept while keeping the empirical error rate among accepted runs at
    or below target_risk (Geifman & El-Yaniv, "selective prediction", 2017).

Why this is the load-bearing piece. An agent that acts when it is "confident"
is only as honest as that word. An agent that acts when its *calibrated*
P(correct) clears a risk-tiered bar — fit on its own verified outcomes — has a
defensible, distribution-free reason for every autonomous action and every
escalation. The calibrator is fit on the receipt flywheel (measured uncertainty
of each past run paired with whether the deterministic verifiers / contract
check said it was correct), so the guarantee tightens as the agent runs.

Pure Python, no numpy/torch — offline-testable like nfet_policy, and the same
code can run inside the receipt path without pulling in the model stack.

Discipline: a selective-risk / conformal guarantee is only valid on data the
threshold was NOT fit on. Fit on a held-out split of the flywheel; ``fit`` here
does not peek at the future. The guarantee is *marginal* (over the exchangeable
log), which is exactly the honest claim — no more.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


def _pav(values: Sequence[float], weights: Sequence[float],
         increasing: bool = True) -> List[float]:
    """Pool Adjacent Violators — isotonic regression in O(n).

    Returns the fitted monotone sequence (non-decreasing if ``increasing``,
    else non-increasing) that minimises weighted squared error against
    ``values`` in the given order.
    """
    # Each block: [weighted_sum, weight, start_idx, end_idx].
    blocks: List[List[float]] = []
    for i, (v, w) in enumerate(zip(values, weights)):
        blocks.append([v * w, w, i, i])
        while len(blocks) >= 2:
            a, c = blocks[-2], blocks[-1]
            mean_a, mean_c = a[0] / a[1], c[0] / c[1]
            violates = (mean_a > mean_c) if increasing else (mean_a < mean_c)
            if not violates:
                break
            blocks[-2] = [a[0] + c[0], a[1] + c[1], a[2], c[3]]
            blocks.pop()
    fitted = [0.0] * len(values)
    for b in blocks:
        mean = b[0] / b[1]
        for k in range(int(b[2]), int(b[3]) + 1):
            fitted[k] = mean
    return fitted


@dataclass
class UncertaintyCalibrator:
    """Maps a scalar uncertainty U (higher = less sure) to P(correct | U).

    Fit with isotonic regression constrained NON-INCREASING in U: more measured
    uncertainty can never map to a higher modelled probability of being right.
    That monotonicity is the honest prior — it makes the calibrator auditable
    (no pockets where "more confused" reads as "more correct") and stable on
    small flywheels.
    """

    # Breakpoints, ascending in U, with the fitted P(correct) at each.
    us: List[float] = field(default_factory=list)
    ps: List[float] = field(default_factory=list)
    n_fit: int = 0

    def fit(self, uncertainties: Sequence[float],
            correct: Sequence[int]) -> "UncertaintyCalibrator":
        """Fit P(correct | U) from logged (uncertainty, was_correct) pairs."""
        pairs = sorted(
            (float(u), 1.0 if c else 0.0)
            for u, c in zip(uncertainties, correct)
            if u is not None and not math.isnan(float(u))
        )
        if not pairs:
            self.us, self.ps, self.n_fit = [], [], 0
            return self
        us = [u for u, _ in pairs]
        ys = [y for _, y in pairs]
        fitted = _pav(ys, [1.0] * len(ys), increasing=False)
        # Collapse consecutive equal-U points to the last fitted value.
        self.us, self.ps = [], []
        for u, p in zip(us, fitted):
            if self.us and u == self.us[-1]:
                self.ps[-1] = p
            else:
                self.us.append(u)
                self.ps.append(p)
        self.n_fit = len(pairs)
        return self

    def p_correct(self, u: float) -> float:
        """Calibrated probability of correctness at uncertainty ``u``.

        Piecewise-constant step function (the isotonic fit). Clamps to the
        endpoints outside the observed range — never extrapolates optimism.
        """
        if not self.us:
            return _default_p_correct(u)  # uncalibrated prior
        if u <= self.us[0]:
            return self.ps[0]
        if u >= self.us[-1]:
            return self.ps[-1]
        # Binary search for the last breakpoint <= u.
        lo, hi = 0, len(self.us) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.us[mid] <= u:
                lo = mid
            else:
                hi = mid - 1
        return self.ps[lo]

    @property
    def is_fit(self) -> bool:
        return bool(self.us)


def _default_p_correct(u: float) -> float:
    """Conservative uncalibrated prior, used until a flywheel exists.

    A monotone-decreasing map of a z-scored uncertainty to a probability,
    deliberately pessimistic (escalate sooner) so an UNCALIBRATED agent never
    acts autonomously on a high-risk action by accident. This is a prior to be
    replaced by ``UncertaintyCalibrator.fit`` on real outcomes — not a claim.
    """
    # Logistic centred so U~0 (typical) -> ~0.8 and U>=2 (clearly elevated)
    # -> <0.3. Pessimistic slope on purpose.
    return 1.0 / (1.0 + math.exp(1.4 * (u - 0.5)))


@dataclass
class SelectiveThreshold:
    """Result of a selective-risk fit: accept iff U <= tau."""

    tau: float
    coverage: float          # fraction of the log we would act on
    empirical_risk: float    # error rate among accepted (<= target if feasible)
    target_risk: float
    feasible: bool           # False => even the most certain run is too risky
    n: int


def selective_threshold(uncertainties: Sequence[float], correct: Sequence[int],
                        target_risk: float) -> SelectiveThreshold:
    """Largest uncertainty we may accept while empirical error <= target_risk.

    Selective prediction (Geifman & El-Yaniv 2017): order runs by uncertainty
    and accept a low-uncertainty prefix. ``tau`` is the highest U whose accepted
    prefix keeps the error rate at or below ``target_risk``; coverage is how
    much of the log that prefix is. Returns ``feasible=False`` when no non-empty
    prefix meets the bar (the honest answer: this risk tier cannot be automated
    on current evidence — escalate everything).

    For a valid guarantee on future runs, fit this on a held-out split.
    """
    pairs = sorted(
        (float(u), 1 if c else 0)
        for u, c in zip(uncertainties, correct)
        if u is not None and not math.isnan(float(u))
    )
    n = len(pairs)
    if n == 0:
        return SelectiveThreshold(float("-inf"), 0.0, 0.0, target_risk, False, 0)
    best: Optional[SelectiveThreshold] = None
    errors = 0
    for k, (u, c) in enumerate(pairs, start=1):
        errors += (1 - c)
        risk = errors / k
        if risk <= target_risk:
            best = SelectiveThreshold(u, k / n, risk, target_risk, True, n)
    if best is None:
        # Not even the single most-certain run clears the bar.
        return SelectiveThreshold(pairs[0][0] - 1e9, 0.0,
                                  1 - pairs[0][1], target_risk, False, n)
    return best


def aggregate_uncertainty(frames: Sequence[Dict[str, float]],
                          low_conf_span_fraction: Optional[float] = None) -> float:
    """Collapse a run's per-token telemetry into ONE scalar U (higher = less sure).

    The honest aggregate the gate consumes. Defined and documented so it is
    reproducible from a receipt, not a black box:

        U = mean(entropy z-proxy) + 0.5 * max(0, drift z-proxy)
            + (low_conf_span_fraction or 0)

    Uses graft_entropy/hidden_drift if present. Returns 0.0 (maximally certain)
    when there is no telemetry at all — the caller MUST treat "no telemetry" as
    its own escalation case, not as confidence.
    """
    if not frames:
        return 0.0
    ent = [float(f.get("graft_entropy", f.get("logit_entropy", 0.0))) for f in frames]
    drift = [float(f.get("hidden_drift", 0.0)) for f in frames]
    if not ent:
        return 0.0
    mu = sum(ent) / len(ent)
    var = sum((e - mu) ** 2 for e in ent) / max(len(ent) - 1, 1)
    sd = math.sqrt(max(var, 1e-12))
    # z of the *worst* third of tokens vs the run's own mean — sustained spikes,
    # not single outliers.
    tail = sorted(ent, reverse=True)[: max(1, len(ent) // 3)]
    ent_z = (sum(tail) / len(tail) - mu) / sd if sd > 1e-9 else 0.0
    dmu = sum(drift) / len(drift) if drift else 0.0
    dvar = sum((d - dmu) ** 2 for d in drift) / max(len(drift) - 1, 1) if drift else 0.0
    dsd = math.sqrt(max(dvar, 1e-12))
    drift_z = (max(drift) - dmu) / dsd if drift and dsd > 1e-9 else 0.0
    u = max(0.0, ent_z) + 0.5 * max(0.0, drift_z)
    if low_conf_span_fraction:
        u += float(low_conf_span_fraction)
    return round(u, 4)
