# Copyright (c) 2026 Qira LLC. All rights reserved.
"""NFET controller weights + thresholds — config, logged in every receipt.

These are the exact coefficients from the control spec. They live here (not
inline) so a receipt can record them and the technical trace can show them: the
controller's behaviour is a function of numbers you can read, not a black box.
Tune in one place; every decision and receipt reflects the change.
"""

from __future__ import annotations

CONTROLLER_VERSION = "nfet-control-1.0.0"

# Fused uncertainty: U_total = σ(Σ w_i · signal_i + b).
NFET_WEIGHTS = {
    "surfaceUncertainty": 0.22,
    "latentUncertainty": 0.22,
    "entropy": 0.14,
    "drift": 0.14,
    "contradictionRisk": 0.16,
    "verificationNeed": 0.08,
    "bias": -0.18,
}

# Event-field energy: E_field = Σ α_i · spike_i − α_cost·costPressure − α_safe·safetyRisk.
NFET_FIELD_WEIGHTS = {
    "uncertainty": 0.24,
    "drift": 0.14,
    "contradiction": 0.18,
    "memoryPressure": 0.10,
    "goalPressure": 0.12,
    "verificationNeed": 0.12,
    "toolNeed": 0.08,
    "costPressure": 0.10,   # subtracted
    "safetyRisk": 0.30,     # subtracted
}

# Decision thresholds. idle/refuse gate the whole field; the per-action values
# are the score an action must cross to be eligible.
NFET_THRESHOLDS = {
    "idle": 0.22,
    "act": 0.48,
    "verify": 0.56,
    "retrieve": 0.52,
    "branch": 0.58,
    "nudge": 0.72,
    "refuseSafety": 0.80,
    "finish": 0.38,
}

# Action scoring: Score(a) = Σ β · value(a) − penalties.
ACTION_SCORE_WEIGHTS = {
    "goal": 0.18,
    "epistemic": 0.22,
    "memory": 0.12,
    "user": 0.16,
    "verify": 0.14,
    "trace": 0.08,
    "cost": 0.10,
    "risk": 0.30,
    "interrupt": 0.16,
}

VERIFICATION_WEIGHTS = {
    "uncertainty": 0.28,
    "contradiction": 0.22,
    "claimRisk": 0.20,
    "freshnessRisk": 0.14,
    "userImpact": 0.16,
}

RETRIEVAL_WEIGHTS = {
    "uncertainty": 0.30,
    "memoryGap": 0.24,
    "openQuestion": 0.22,
    "goalPressure": 0.24,
}

BRANCH_WEIGHTS = {
    "drift": 0.30,
    "uncertainty": 0.26,
    "contradiction": 0.24,
    "lowConfidenceSpanDensity": 0.20,
}

MEMORY_WRITE_WEIGHTS = {
    "goal": 0.20,
    "future": 0.22,
    "user": 0.18,
    "fact": 0.16,
    "novelty": 0.12,
    "privacy": 0.30,    # subtracted
    "duplicate": 0.18,  # subtracted
}

MEMORY_THRESHOLDS = {
    "write": 0.62,
    "project": 0.70,
    "longTerm": 0.82,
}

# Event-field rolling-z parameters. KAPPA is the z a signal must exceed to count
# as a spike; the PRIOR_* seed the rolling stats so a cold controller still reacts
# to a clearly elevated raw signal instead of needing history first.
FIELD_KAPPA = 1.0
PRIOR_MEAN = 0.35
PRIOR_STD = 0.18
EPS = 1e-6
