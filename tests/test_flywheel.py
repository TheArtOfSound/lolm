# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the autonomy flywheel (uncertainty, verified outcome) log."""

from lolm.flywheel import AutonomyFlywheel


def test_record_and_count(tmp_path):
    fw = AutonomyFlywheel(tmp_path / "fw.jsonl", min_fit=5)
    assert fw.count == 0
    assert fw.record(0.2, True) is True
    assert fw.record(1.5, False) is True
    assert fw.count == 2


def test_record_noop_on_missing_signal(tmp_path):
    fw = AutonomyFlywheel(tmp_path / "fw.jsonl")
    assert fw.record(None, True) is False        # no uncertainty
    assert fw.record(0.3, None) is False         # no outcome label
    assert fw.count == 0


def test_calibrator_none_until_min_fit(tmp_path):
    fw = AutonomyFlywheel(tmp_path / "fw.jsonl", min_fit=10)
    for i in range(8):
        fw.record(0.1 * i, i % 2 == 0)
    assert fw.calibrator() is None               # too little track record
    for i in range(8, 12):
        fw.record(0.1 * i, i % 2 == 0)
    assert fw.calibrator() is not None           # earns calibration


def test_calibrator_learns_monotone(tmp_path):
    fw = AutonomyFlywheel(tmp_path / "fw.jsonl", min_fit=10, refit_every=1)
    for u in [0.0, 0.2, 0.5, 1.0, 2.0]:
        for _ in range(10):
            fw.record(u, u < 0.6)                 # certain runs correct, unsure wrong
    cal = fw.calibrator()
    assert cal is not None
    assert cal.p_correct(0.0) > cal.p_correct(2.0)


def test_selective_bar_and_stats(tmp_path):
    fw = AutonomyFlywheel(tmp_path / "fw.jsonl", min_fit=1)
    for i in range(100):
        fw.record(i / 100.0, i < 90)
    bar = fw.selective_bar(target_risk=0.05)
    assert bar.feasible and bar.empirical_risk <= 0.05 + 1e-9
    st = fw.stats()
    assert st["n"] == 100 and st["calibrated"] is True


def test_durable_across_instances(tmp_path):
    p = tmp_path / "fw.jsonl"
    AutonomyFlywheel(p).record(0.4, True)
    assert AutonomyFlywheel(p).count == 1         # reads what the prior wrote
