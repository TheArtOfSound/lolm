from __future__ import annotations

import random

from lolm.nfet_policy import (
    CONTROL_BRANCH,
    CONTROL_CONTINUE,
    CONTROL_FINALIZE,
    CONTROL_RETRIEVE,
    CONTROL_VERIFY,
    NFETControlPolicy,
    PolicyConfig,
    TelemetryFrame,
    frames_from_chat_trace,
    label_trace,
)


def make_frames(n: int, entropy: float = 3.0, drift: float = 0.05,
                gate: float = 0.7, regime: float = 2.0, start: int = 1,
                jitter: float = 0.02, seed: int = 0) -> list[TelemetryFrame]:
    rng = random.Random(seed)
    return [
        TelemetryFrame(
            logit_entropy=entropy + rng.uniform(-jitter, jitter),
            hidden_drift=drift + rng.uniform(-jitter, jitter) * 0.1,
            gate_mean=gate + rng.uniform(-jitter, jitter) * 0.1,
            regime_entropy=regime + rng.uniform(-jitter, jitter),
            step=start + i,
        )
        for i in range(n)
    ]


def test_calibration_warmup_forces_continue():
    policy = NFETControlPolicy(PolicyConfig(min_calibration=12))
    policy.observe_all(make_frames(5))
    decision = policy.decide()
    assert decision.control == CONTROL_CONTINUE
    assert decision.source == "calibrating"


def test_entropy_spike_triggers_retrieve():
    cfg = PolicyConfig(min_calibration=12, sustain=4, cooldown=8)
    policy = NFETControlPolicy(cfg)
    policy.observe_all(make_frames(30, entropy=3.0))
    # sustained spike well above the rolling distribution
    policy.observe_all(make_frames(4, entropy=6.5, start=31))
    decision = policy.decide()
    assert decision.control == CONTROL_RETRIEVE
    assert decision.source == "heuristic"
    assert "uncertainty" in decision.reason


def test_drift_spike_triggers_verify():
    cfg = PolicyConfig(min_calibration=12, sustain=4, cooldown=8)
    policy = NFETControlPolicy(cfg)
    policy.observe_all(make_frames(30, drift=0.05, entropy=3.0))
    policy.observe_all(make_frames(4, drift=0.6, entropy=3.6, start=31))
    decision = policy.decide()
    assert decision.control == CONTROL_VERIFY


def test_regime_collapse_triggers_branch():
    cfg = PolicyConfig(min_calibration=12, sustain=4, cooldown=8)
    policy = NFETControlPolicy(cfg)
    policy.observe_all(make_frames(30, regime=2.5, entropy=3.0))
    policy.observe_all(make_frames(4, regime=0.2, entropy=3.05, start=31))
    decision = policy.decide()
    assert decision.control == CONTROL_BRANCH


def test_calm_confident_run_finalizes():
    cfg = PolicyConfig(min_calibration=12, sustain=4, cooldown=8,
                       min_steps_before_finalize=24)
    policy = NFETControlPolicy(cfg)
    policy.observe_all(make_frames(40, entropy=3.0, drift=0.05))
    policy.observe_all(make_frames(6, entropy=1.2, drift=0.01, start=41))
    decision = policy.decide()
    assert decision.control == CONTROL_FINALIZE


def test_cooldown_prevents_thrash():
    cfg = PolicyConfig(min_calibration=12, sustain=4, cooldown=16)
    policy = NFETControlPolicy(cfg)
    policy.observe_all(make_frames(30, entropy=3.0))
    policy.observe_all(make_frames(4, entropy=6.5, start=31))
    first = policy.decide()
    assert first.control == CONTROL_RETRIEVE
    policy.observe_all(make_frames(2, entropy=6.5, start=35))
    second = policy.decide()
    assert second.control == CONTROL_CONTINUE
    assert second.source == "cooldown"


def test_trained_head_overrides_when_confident():
    cfg = PolicyConfig(min_calibration=4, cooldown=4, head_confidence=0.5)
    policy = NFETControlPolicy(cfg)
    policy.observe_all(make_frames(20))
    # head strongly prefers verify
    logits = [0.0, 0.0, 6.0, 0.0, 0.0]
    decision = policy.decide(control_logits=logits, head_trained=True)
    assert decision.control == CONTROL_VERIFY
    assert decision.source == "head"
    # unconfident head falls back to heuristic
    policy2 = NFETControlPolicy(cfg)
    policy2.observe_all(make_frames(20))
    flat = [0.1, 0.1, 0.1, 0.1, 0.1]
    decision2 = policy2.decide(control_logits=flat, head_trained=True)
    assert decision2.source != "head"


def test_untrained_head_is_ignored():
    cfg = PolicyConfig(min_calibration=4, cooldown=4)
    policy = NFETControlPolicy(cfg)
    policy.observe_all(make_frames(20))
    logits = [0.0, 0.0, 9.0, 0.0, 0.0]
    decision = policy.decide(control_logits=logits, head_trained=False)
    assert decision.source != "head"


def test_label_trace_produces_per_frame_labels():
    frames = make_frames(30, entropy=3.0) + make_frames(6, entropy=6.5, start=31)
    labels = label_trace(frames, PolicyConfig(min_calibration=12, sustain=4, cooldown=8))
    assert len(labels) == len(frames)
    assert all(0 <= l <= 4 for l in labels)
    assert CONTROL_RETRIEVE in labels[30:]


def test_frames_from_chat_trace_filters_non_graft_tokens():
    trace = [
        {"step": 1, "used_graft": True, "graft_entropy": 3.2, "hidden_drift": 0.1,
         "gate_mean": 0.7, "regime_entropy": 2.0},
        {"step": 2, "used_graft": False, "base_entropy": 9.9},
        {"step": 3, "used_graft": True, "graft_entropy": 3.0, "hidden_drift": 0.12,
         "gate_mean": 0.71, "regime_entropy": 2.1},
    ]
    frames = frames_from_chat_trace(trace)
    assert len(frames) == 2
    assert frames[0].logit_entropy == 3.2
    assert frames[1].step == 3
