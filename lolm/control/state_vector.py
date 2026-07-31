# Copyright (c) 2026 Qira LLC. All rights reserved.
"""NFET state vector s_t — compact control state for closed-loop governance.

Each field has a definition, measurement method, and known limitations.
Proxy measurements (no graft) are honest encodings of sandbox evidence, not
fake confidence.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class NfetStateVector:
    """s_t used by the controller policy.

    Fields align with the product brief:
      u uncertainty, d drift/contradiction, n novelty, m memory relevance,
      v verification need, r repetition risk, q task-quality estimate,
      b remaining budget, c contract pressure, regime discrete id.
    """

    uncertainty: float = 0.0
    drift: float = 0.0
    novelty: float = 0.0
    memory_relevance: float = 0.0
    verification_need: float = 0.0
    repetition_risk: float = 0.0
    quality: float = 0.0
    budget: float = 1.0
    contract_pressure: float = 0.0
    regime: str = "unknown"
    source: str = "empty"  # graft | synthetic | mixed
    step: int = 0
    extras: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def feature_list(self) -> List[float]:
        """Fixed-order features for ML heads."""
        return [
            self.uncertainty, self.drift, self.novelty, self.memory_relevance,
            self.verification_need, self.repetition_risk, self.quality,
            self.budget, self.contract_pressure,
        ]


_REGIMES = (
    "fluent", "evidence_deficit", "high_uncertainty", "thrash",
    "verification_required", "completion_ready", "unsafe",
)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def estimate_from_sandbox(
    *,
    exit_ok: bool = False,
    thrash: int = 0,
    green_runs: int = 0,
    failed_runs: int = 0,
    contract_failed: bool = False,
    budget_frac_used: float = 0.0,
    stderr: str = "",
    stdout: str = "",
    step: int = 0,
    memory_hits: int = 0,
    memory_used: int = 0,
) -> NfetStateVector:
    """Proxy state when graft telemetry is unavailable."""
    total = max(green_runs + failed_runs, 1)
    err = (stderr or "").lower()
    # Uncertainty
    if not exit_ok:
        u = 0.75 + min(thrash, 3) * 0.08
    elif contract_failed:
        u = 0.65
    elif green_runs >= 2 and failed_runs == 0:
        u = 0.2
    else:
        u = 0.4
    # Drift
    if "syntaxerror" in err or "indentationerror" in err:
        d = 0.85
    elif "assertionerror" in err or "traceback" in err:
        d = 0.6
    elif not exit_ok:
        d = 0.5
    elif contract_failed:
        d = 0.45
    else:
        d = 0.1
    # Novelty: crude — empty stdout / first fail
    n = 0.7 if failed_runs <= 1 and not exit_ok else 0.3
    # Memory
    m = (memory_used / memory_hits) if memory_hits > 0 else 0.0
    # Verification need
    v = 1.0 if (contract_failed or thrash >= 1 or not exit_ok) else 0.15
    # Repetition / thrash
    r = _clip01(thrash / 3.0)
    # Quality
    q = green_runs / total if exit_ok and not contract_failed else green_runs / (total + 1)
    # Budget remaining
    b = _clip01(1.0 - budget_frac_used)
    # Contract
    c = 1.0 if contract_failed else 0.0

    regime = "unknown"
    if thrash >= 2:
        regime = "thrash"
    elif contract_failed or (exit_ok and c > 0):
        regime = "verification_required"
    elif not exit_ok and failed_runs > 0:
        regime = "high_uncertainty"
    elif exit_ok and not contract_failed and green_runs >= 1:
        regime = "completion_ready"
    elif memory_hits == 0 and not exit_ok:
        regime = "evidence_deficit"
    else:
        regime = "fluent"

    return NfetStateVector(
        uncertainty=_clip01(u), drift=_clip01(d), novelty=_clip01(n),
        memory_relevance=_clip01(m), verification_need=_clip01(v),
        repetition_risk=r, quality=_clip01(q), budget=b,
        contract_pressure=c, regime=regime, source="synthetic", step=step,
    )


def estimate_from_frames(
    frames: Sequence[Dict[str, Any]],
    *,
    sandbox: Optional[NfetStateVector] = None,
    step: int = 0,
) -> NfetStateVector:
    """Blend graft frame stats with optional sandbox prior."""
    if not frames:
        return sandbox or NfetStateVector(source="empty", step=step)
    ent, drift, gate, reg = [], [], [], []
    for f in frames:
        if not isinstance(f, dict):
            continue
        ent.append(float(f.get("graft_entropy") or f.get("logit_entropy") or 0.0))
        drift.append(float(f.get("hidden_drift") or 0.0))
        gate.append(float(f.get("gate_mean") or 0.0))
        reg.append(float(f.get("regime_entropy") or 0.0))
    if not ent:
        return sandbox or NfetStateVector(source="empty", step=step)

    def mean(xs: List[float]) -> float:
        return sum(xs) / len(xs)

    # Map raw nats / drifts into [0,1]-ish control features.
    u = _clip01((mean(ent) - 1.0) / 4.0)
    d = _clip01(mean(drift) * 5.0)
    # High regime entropy ≈ exploring; low ≈ stuck (invert for "stall risk")
    stall = _clip01(1.0 - mean(reg) / 3.0)

    base = sandbox or NfetStateVector()
    return NfetStateVector(
        uncertainty=max(u, base.uncertainty * 0.5),
        drift=max(d, base.drift * 0.5),
        novelty=base.novelty,
        memory_relevance=base.memory_relevance,
        verification_need=max(u * 0.8 + d * 0.4, base.verification_need),
        repetition_risk=max(stall * 0.6, base.repetition_risk),
        quality=base.quality,
        budget=base.budget,
        contract_pressure=base.contract_pressure,
        regime=base.regime if base.regime != "unknown" else (
            "thrash" if stall > 0.7 and u > 0.5 else
            "high_uncertainty" if u > 0.6 else
            "completion_ready" if u < 0.3 and d < 0.2 else "fluent"
        ),
        source="mixed" if sandbox else "graft",
        step=step,
        extras={"gate_mean": mean(gate), "regime_entropy": mean(reg)},
    )
