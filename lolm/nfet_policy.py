"""NFET control policy — turns latent telemetry into agent control decisions.

This module closes the loop the rest of the repository prepares for: the
``NFETController`` head emits control logits over five actions, and the
generation loop streams per-token observables (logit entropy, hidden drift,
gate mean, regime entropy). Until the head is trained, those logits are
random-init noise — so this policy provides a calibrated heuristic that maps
observables to decisions, and doubles as the weak labeler that produces
training targets for the head.

Decision semantics:
    0 continue  — trajectory is healthy, keep generating
    1 retrieve  — sustained uncertainty: go get evidence (memory/web)
    2 verify    — representation jumped while uncertain: check the draft
    3 branch    — regime collapsed into a rut while not confident: explore
    4 finalize  — confident and stable: wrap up

Everything here is pure Python on floats so it runs without torch and is
fully offline-testable. The same logic labels recorded traces for weak
supervision of the controller head.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence

CONTROL_CONTINUE = 0
CONTROL_RETRIEVE = 1
CONTROL_VERIFY = 2
CONTROL_BRANCH = 3
CONTROL_FINALIZE = 4

CONTROL_LABELS = {
    CONTROL_CONTINUE: "continue",
    CONTROL_RETRIEVE: "retrieve",
    CONTROL_VERIFY: "verify",
    CONTROL_BRANCH: "branch",
    CONTROL_FINALIZE: "finalize",
}


@dataclass
class TelemetryFrame:
    """One step of NFET observables, as produced by the generation loop."""

    logit_entropy: float = 0.0
    hidden_drift: float = 0.0
    gate_mean: float = 0.0
    regime_entropy: float = 0.0
    step: int = 0

    @classmethod
    def from_trace(cls, trace: Dict, step: int = 0) -> "TelemetryFrame":
        """Build a frame from a generation-loop token trace dict."""
        def num(key: str, *fallbacks: str) -> float:
            for k in (key, *fallbacks):
                value = trace.get(k)
                if isinstance(value, (int, float)) and not math.isnan(float(value)):
                    return float(value)
            return 0.0

        return cls(
            logit_entropy=num("graft_entropy", "base_entropy", "logit_entropy"),
            hidden_drift=num("hidden_drift"),
            gate_mean=num("gate_mean"),
            regime_entropy=num("regime_entropy"),
            step=int(trace.get("step", step)),
        )


@dataclass
class PolicyConfig:
    """Calibration thresholds for the heuristic control policy.

    Thresholds are z-scores against a rolling window of the run's own
    telemetry, so the policy adapts to each backbone/graft pair instead of
    requiring absolute tuning per model.
    """

    window: int = 160                # rolling calibration window; must span
                                     # several segments so cross-segment shifts
                                     # (e.g. a calm closing segment) stay visible
    min_calibration: int = 12        # frames before any non-continue decision
    sustain: int = 4                 # consecutive frames needed over threshold
    cooldown: int = 16               # frames forced to continue after an action

    entropy_spike_z: float = 1.25    # sustained high entropy -> retrieve
    drift_spike_z: float = 1.75      # drift spike while uncertain -> verify
    verify_entropy_z: float = 0.25   # entropy support needed for verify
    regime_stall_z: float = -1.25    # regime entropy collapse -> branch
    branch_entropy_z: float = -0.5   # entropy must not be deeply low for branch
    finalize_entropy_z: float = -1.0 # calm + confident -> finalize eligible
    finalize_drift_z: float = 0.0
    min_steps_before_finalize: int = 32

    head_confidence: float = 0.55    # trained-head prob needed to take over
    use_trained_head: bool = True

    # Std floors prevent noise-amplified spikes: when a run's telemetry is
    # very flat, a tiny absolute wiggle should not register as a z-spike.
    entropy_std_floor: float = 0.20  # nats
    drift_std_floor: float = 0.02
    gate_std_floor: float = 0.02
    regime_std_floor: float = 0.15


@dataclass
class ControlDecision:
    control: int
    label: str
    source: str                      # "heuristic" | "head" | "calibrating" | "cooldown"
    reason: str
    zscores: Dict[str, float] = field(default_factory=dict)
    head_probs: Optional[List[float]] = None
    step: int = 0

    def to_dict(self) -> Dict:
        return {
            "control": self.control,
            "label": self.label,
            "source": self.source,
            "reason": self.reason,
            "zscores": {k: round(v, 3) for k, v in self.zscores.items()},
            "head_probs": [round(p, 4) for p in self.head_probs] if self.head_probs else None,
            "step": self.step,
        }


class RollingStats:
    """Numerically simple rolling mean/std over a fixed window."""

    def __init__(self, window: int):
        self.values: Deque[float] = deque(maxlen=window)

    def push(self, value: float) -> None:
        if math.isnan(value) or math.isinf(value):
            return
        self.values.append(float(value))

    def __len__(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0

    @property
    def std(self) -> float:
        n = len(self.values)
        if n < 2:
            return 0.0
        mu = self.mean
        var = sum((v - mu) ** 2 for v in self.values) / (n - 1)
        return math.sqrt(max(var, 0.0))

    def zscore(self, value: float, std_floor: float = 0.0) -> float:
        std = max(self.std, std_floor)
        if std < 1e-8:
            return 0.0
        return (value - self.mean) / std

    def freeze(self) -> "FrozenStats":
        return FrozenStats(mean=self.mean, std=self.std, count=len(self.values))


@dataclass
class FrozenStats:
    """Point-in-time snapshot of a rolling distribution."""

    mean: float = 0.0
    std: float = 0.0
    count: int = 0

    def zscore(self, value: float, std_floor: float = 0.0) -> float:
        std = max(self.std, std_floor)
        if std < 1e-8:
            return 0.0
        return (value - self.mean) / std


def softmax(logits: Sequence[float]) -> List[float]:
    if not logits:
        return []
    peak = max(logits)
    exps = [math.exp(min(l - peak, 60.0)) for l in logits]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


class NFETControlPolicy:
    """Calibrated controller: heuristic baseline, trained head override.

    Usage in a loop:
        policy = NFETControlPolicy()
        for frame in frames:
            policy.observe(frame)
        decision = policy.decide(control_logits=..., head_trained=...)
    """

    def __init__(self, config: Optional[PolicyConfig] = None):
        self.cfg = config or PolicyConfig()
        self.entropy = RollingStats(self.cfg.window)
        self.drift = RollingStats(self.cfg.window)
        self.gate = RollingStats(self.cfg.window)
        self.regime = RollingStats(self.cfg.window)
        self.frames_seen = 0
        self.last_action_at = -10_000
        self.recent: Deque[TelemetryFrame] = deque(maxlen=max(self.cfg.sustain, 8))
        self.baseline: Dict[str, FrozenStats] = {}

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------
    def _snapshot_baseline(self) -> None:
        """Freeze the pre-batch distribution so a sustained shift in the new
        batch is judged against history instead of polluting its own baseline."""
        self.baseline = {
            "entropy": self.entropy.freeze(),
            "drift": self.drift.freeze(),
            "gate": self.gate.freeze(),
            "regime": self.regime.freeze(),
        }

    def observe(self, frame: TelemetryFrame) -> None:
        self._snapshot_baseline()
        self._push(frame)

    def observe_all(self, frames: Sequence[TelemetryFrame]) -> None:
        if not frames:
            return
        self._snapshot_baseline()
        for frame in frames:
            self._push(frame)

    def _push(self, frame: TelemetryFrame) -> None:
        self.entropy.push(frame.logit_entropy)
        self.drift.push(frame.hidden_drift)
        self.gate.push(frame.gate_mean)
        self.regime.push(frame.regime_entropy)
        self.recent.append(frame)
        self.frames_seen += 1

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------
    def _sustained_z(self, key: str, live: RollingStats, attr: str, std_floor: float) -> float:
        """Mean z-score of the last `sustain` frames against the pre-batch
        baseline (falls back to live stats while the baseline is too small)."""
        if not self.recent:
            return 0.0
        stats = self.baseline.get(key)
        if stats is None or stats.count < max(self.cfg.min_calibration // 2, 4):
            stats = live
        tail = list(self.recent)[-self.cfg.sustain:]
        scores = [stats.zscore(getattr(f, attr), std_floor) for f in tail]
        return sum(scores) / len(scores)

    def current_zscores(self) -> Dict[str, float]:
        return {
            "entropy": self._sustained_z("entropy", self.entropy, "logit_entropy", self.cfg.entropy_std_floor),
            "drift": self._sustained_z("drift", self.drift, "hidden_drift", self.cfg.drift_std_floor),
            "gate": self._sustained_z("gate", self.gate, "gate_mean", self.cfg.gate_std_floor),
            "regime": self._sustained_z("regime", self.regime, "regime_entropy", self.cfg.regime_std_floor),
        }

    def _heuristic(self, z: Dict[str, float]) -> ControlDecision:
        cfg = self.cfg
        step = self.recent[-1].step if self.recent else self.frames_seen

        if self.frames_seen < cfg.min_calibration:
            return ControlDecision(
                CONTROL_CONTINUE, "continue", "calibrating",
                f"calibrating ({self.frames_seen}/{cfg.min_calibration} frames)",
                z, step=step,
            )
        if self.frames_seen - self.last_action_at < cfg.cooldown:
            return ControlDecision(
                CONTROL_CONTINUE, "continue", "cooldown",
                f"cooldown ({self.frames_seen - self.last_action_at}/{cfg.cooldown} frames since last action)",
                z, step=step,
            )

        # Priority order: verify > retrieve > branch > finalize > continue.
        if z["drift"] >= cfg.drift_spike_z and z["entropy"] >= cfg.verify_entropy_z:
            return ControlDecision(
                CONTROL_VERIFY, "verify", "heuristic",
                f"hidden drift spiked (z={z['drift']:.2f}) while uncertain (entropy z={z['entropy']:.2f}) — check the draft",
                z, step=step,
            )
        if z["entropy"] >= cfg.entropy_spike_z:
            return ControlDecision(
                CONTROL_RETRIEVE, "retrieve", "heuristic",
                f"sustained uncertainty (entropy z={z['entropy']:.2f}) — fetch evidence",
                z, step=step,
            )
        if z["regime"] <= cfg.regime_stall_z and z["entropy"] >= cfg.branch_entropy_z:
            return ControlDecision(
                CONTROL_BRANCH, "branch", "heuristic",
                f"regime collapse (z={z['regime']:.2f}) while not confident — explore alternatives",
                z, step=step,
            )
        if (
            self.frames_seen >= cfg.min_steps_before_finalize
            and z["entropy"] <= cfg.finalize_entropy_z
            and z["drift"] <= cfg.finalize_drift_z
        ):
            return ControlDecision(
                CONTROL_FINALIZE, "finalize", "heuristic",
                f"confident and stable (entropy z={z['entropy']:.2f}, drift z={z['drift']:.2f}) — wrap up",
                z, step=step,
            )
        return ControlDecision(
            CONTROL_CONTINUE, "continue", "heuristic", "trajectory healthy", z, step=step,
        )

    def decide(
        self,
        control_logits: Optional[Sequence[float]] = None,
        head_trained: bool = False,
    ) -> ControlDecision:
        """Pick the next control action.

        A trained head takes over when it is confident; otherwise the
        calibrated heuristic decides. Cooldown and calibration warmup apply
        to both paths so neither can thrash the loop.
        """
        z = self.current_zscores()
        decision = self._heuristic(z)

        if (
            head_trained
            and self.cfg.use_trained_head
            and control_logits is not None
            and len(control_logits) == len(CONTROL_LABELS)
            and decision.source not in ("calibrating", "cooldown")
        ):
            probs = softmax(list(control_logits))
            best = max(range(len(probs)), key=probs.__getitem__)
            if probs[best] >= self.cfg.head_confidence:
                decision = ControlDecision(
                    best, CONTROL_LABELS[best], "head",
                    f"trained head confident (p={probs[best]:.2f})",
                    z, head_probs=probs,
                    step=self.recent[-1].step if self.recent else self.frames_seen,
                )
            else:
                decision.head_probs = probs

        if decision.control != CONTROL_CONTINUE:
            self.last_action_at = self.frames_seen
        return decision


def label_trace_decisions(
    frames: Sequence[TelemetryFrame],
    config: Optional[PolicyConfig] = None,
) -> List[ControlDecision]:
    """Replay the heuristic over a trace, returning the full decisions.

    The decision ``source`` lets a trainer drop frames whose label depends on
    hidden run-state (cooldown/calibration) that a pointwise head cannot see.
    """
    policy = NFETControlPolicy(config)
    decisions: List[ControlDecision] = []
    for frame in frames:
        policy.observe(frame)
        decisions.append(policy.decide(control_logits=None, head_trained=False))
    return decisions


def label_trace(
    frames: Sequence[TelemetryFrame],
    config: Optional[PolicyConfig] = None,
) -> List[int]:
    """Weak labels for controller training: replay the heuristic over a trace.

    Returns one control id per frame. This is the supervision signal that
    turns logged workspace traffic into training data for the control head.
    """
    return [d.control for d in label_trace_decisions(frames, config)]


def frames_from_chat_trace(trace: Sequence[Dict]) -> List[TelemetryFrame]:
    """Extract telemetry frames from a logged chat entry's token trace."""
    frames: List[TelemetryFrame] = []
    for i, token_trace in enumerate(trace):
        if not isinstance(token_trace, dict):
            continue
        if not token_trace.get("used_graft"):
            continue
        frames.append(TelemetryFrame.from_trace(token_trace, step=i + 1))
    return frames
