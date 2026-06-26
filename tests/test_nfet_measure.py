# Copyright (c) 2026 Qira LLC. All rights reserved.
import math, random
from lolm.nfet_measure import (derive_theta, false_event_rate, spearman, eta_squared,
                               channels_for_sequence, phi, Channels)


def test_theta_hits_target_false_event_rate():
    rng = random.Random(0)
    null = [rng.gauss(0, 1) for _ in range(5000)]
    for alpha in (0.01, 0.05, 0.1):
        theta = derive_theta(null, alpha)
        fer = false_event_rate(null, theta)
        assert abs(fer - alpha) < 0.01, (alpha, fer)


def test_spearman_and_eta():
    assert spearman([1,2,3,4,5],[2,4,6,8,10]) > 0.99       # perfect monotone
    assert abs(spearman([1,2,3,4,5],[5,4,3,2,1]) + 1) < 0.01
    # eta^2 ~1 when groups perfectly separate values, ~0 when they don't
    assert eta_squared([1,1,9,9],[0,0,1,1]) > 0.95
    assert eta_squared([1,9,1,9],[0,0,1,1]) < 0.1


def test_channels_shapes():
    frames = [{"logit_entropy":2.0-0.1*i,"hidden_drift":0.5,"gate_mean":0.3,"regime_entropy":0.4}
              for i in range(12)]
    ch, down = channels_for_sequence(frames, horizon=3)
    assert len(ch) == len(down)
    assert 0 < len(ch) <= len(frames) - 3   # only full-horizon tokens emitted
    assert all(0 <= c.I <= 1 and 0 <= c.P <= 1 for c in ch)
