# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Foundations for closed-loop NFET control (state, executor, contract, trajectory)."""

from pathlib import Path

from lolm.control.state_vector import estimate_from_sandbox, estimate_from_frames
from lolm.control.action_executor import ActionExecutor, ExecutorContext
from lolm.control.contract import check_task_contract
from lolm.control import trajectory


def test_state_vector_thrash_regime():
    s = estimate_from_sandbox(
        exit_ok=False, thrash=2, green_runs=0, failed_runs=3,
        contract_failed=False, budget_frac_used=0.5,
        stderr="AssertionError",
    )
    assert s.regime == "thrash"
    assert s.verification_need > 0.5
    assert s.source == "synthetic"
    assert len(s.feature_list()) == 9


def test_state_vector_completion_ready():
    s = estimate_from_sandbox(
        exit_ok=True, thrash=0, green_runs=3, failed_runs=0,
        contract_failed=False, budget_frac_used=0.2,
    )
    assert s.regime == "completion_ready"
    assert s.quality > 0.5


def test_state_from_frames_mixed():
    frames = [
        {"graft_entropy": 3.5, "hidden_drift": 0.1, "gate_mean": 0.7, "regime_entropy": 1.5},
        {"graft_entropy": 3.6, "hidden_drift": 0.12, "gate_mean": 0.7, "regime_entropy": 1.4},
    ]
    sb = estimate_from_sandbox(exit_ok=False, thrash=0, failed_runs=1)
    s = estimate_from_frames(frames, sandbox=sb)
    assert s.source in ("mixed", "graft")
    assert s.uncertainty > 0


def test_executor_verify_consumed():
    ex = ActionExecutor()
    called = {"n": 0}

    def probe():
        called["n"] += 1
        return {"ok": False, "err": "bad"}

    ctx = ExecutorContext(run_contract=probe)
    res = ex.execute("verify", ctx)
    assert res.consumed is True
    assert called["n"] == 1
    assert "contract" in res.side_effects


def test_executor_finalize_blocked_without_hooks():
    ex = ActionExecutor()
    res = ex.execute("finalize", ExecutorContext(exit_ok=False, contract_ok=False))
    assert res.consumed is False


def test_executor_unknown_not_consumed():
    ex = ActionExecutor()
    res = ex.execute("teleport", ExecutorContext())
    assert res.consumed is False
    assert res.error


def test_contract_static_missing_file():
    r = check_task_contract(
        "Create solution.py defining parse_duration(s)",
        files_on_disk=[],
    )
    assert r.ok is False
    assert any("solution.py" in x for x in r.missing_files) or r.reasons


def test_contract_probe_ok():
    r = check_task_contract(
        "Create solution.py defining f()",
        files_on_disk=["solution.py"],
        run_probe=lambda: {"ok": True},
    )
    assert r.ok is True
    assert r.source == "probe"


def test_trajectory_log(tmp_path, monkeypatch):
    p = tmp_path / "traj.jsonl"
    monkeypatch.setenv("LOLM_NFET_TRAJECTORY", str(p))
    trajectory.init(p)
    trajectory.log_step(
        state={"uncertainty": 0.5}, action="verify", consumed=True,
        cost=1.2, run_id="t1",
    )
    rows = trajectory.tail(10)
    assert len(rows) == 1
    assert rows[0]["action"] == "verify"
    assert rows[0]["consumed"] is True
