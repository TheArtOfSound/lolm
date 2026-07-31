# Copyright (c) 2026 Qira LLC. All rights reserved.
"""NFET coding controller — synthetic path is the always-on floor."""

from local_ui.code_nfet import (
    CodeNFET,
    build_code_nfet,
    retrieve_code_memory,
    _synthetic_frames,
)
from lolm.nfet_policy import CONTROL_BRANCH, CONTROL_FINALIZE, CONTROL_VERIFY


def test_synthetic_frames_encode_failure_as_high_entropy():
    bad = _synthetic_frames(
        exit_ok=False, thrash=2, green_runs=0, failed_runs=3,
        stderr="AssertionError: boom", contract_failed=False, budget_frac=0.5,
    )
    good = _synthetic_frames(
        exit_ok=True, thrash=0, green_runs=3, failed_runs=0,
        stderr="", contract_failed=False, budget_frac=0.2,
    )
    assert sum(f.logit_entropy for f in bad) / len(bad) > \
        sum(f.logit_entropy for f in good) / len(good)


def test_code_nfet_blocks_finalize_on_red_run():
    n = CodeNFET()  # synthetic only
    ctrl = n.checkpoint(
        source="def f():\n    return 1\n",
        task="Create solution.py defining f()",
        exit_ok=False,
        thrash=0,
        green_runs=0,
        failed_runs=1,
        stderr="AssertionError",
        phase="work",
    )
    assert ctrl.decision.control != CONTROL_FINALIZE
    assert not n.allow_finalize(exit_ok=False, contract_ok=False)


def test_code_nfet_thrash_forces_branch():
    n = CodeNFET()
    # Warm up the policy with a few frames so thrash guard can fire.
    for thrash in (0, 1, 2):
        ctrl = n.checkpoint(
            source="def f():\n    return 1\n",
            task="Create solution.py defining f()",
            exit_ok=False,
            thrash=thrash,
            green_runs=0,
            failed_runs=thrash + 1,
            stderr="AssertionError: still broken",
            phase="work",
        )
    assert ctrl.decision.control == CONTROL_BRANCH or ctrl.force_branch
    assert ctrl.nudge and "NFET" in ctrl.nudge


def test_code_nfet_contract_fail_forces_verify():
    n = CodeNFET()
    ctrl = n.checkpoint(
        source="def parse_duration(s):\n    return 0.0\n",
        task="Create solution.py defining parse_duration(s) -> float. "
             "Examples: 'PT1H' -> 3600.0. Raise ValueError for ''.",
        exit_ok=True,
        thrash=0,
        green_runs=1,
        failed_runs=0,
        contract_failed=True,
        phase="work",
    )
    assert ctrl.decision.control == CONTROL_VERIFY or ctrl.force_verify
    assert "verify" in ctrl.nudge.lower() or "CONTRACT" in ctrl.nudge or "VERIFY" in ctrl.nudge


def test_code_nfet_green_result_allows_finalize():
    n = CodeNFET()
    # Warm calibration
    for _ in range(3):
        n.checkpoint(
            source="def f():\n    return 1\nprint(f())\n",
            task="Create solution.py defining f()",
            exit_ok=True, thrash=0, green_runs=2, failed_runs=0,
            phase="work",
        )
    ctrl = n.checkpoint(
        source="def f():\n    return 1\nprint(f())\n",
        task="Create solution.py defining f()",
        exit_ok=True, thrash=0, green_runs=3, failed_runs=0,
        contract_failed=False, phase="result",
    )
    assert n.allow_finalize(exit_ok=True, contract_ok=True)
    assert ctrl.decision.control in (CONTROL_FINALIZE, 0) or not ctrl.block_finalize


def test_receipt_blob_shape():
    n = CodeNFET()
    n.checkpoint(source="x=1\n", task="t", exit_ok=True, thrash=0,
                 green_runs=1, failed_runs=0, phase="work")
    blob = n.receipt_blob()
    assert blob["nfet_coding"] is True
    assert blob["n_decisions"] >= 1
    assert "timeline" in blob
    assert "counts" in blob


def test_build_code_nfet_always_returns_controller():
    n = build_code_nfet(None)
    assert n is not None
    assert n.available_graft is False


def test_agent_wires_nfet_into_receipt(tmp_path):
    from local_ui.sandbox import Sandbox
    from local_ui.code_agent import CodeAgent
    from local_ui.code_nfet import CodeNFET

    sb = Sandbox(tmp_path)
    nfet = CodeNFET()
    seq = iter([
        "FILE: solution.py\n```\ndef go():\n    return 7\nprint(go())\n```\n"
        "RUN: python3 solution.py",
        "DONE: shipped",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None, nfet=nfet)
    events = list(agent.run("Create solution.py defining go()"))
    notes = [e for e in events if e["event"] == "agent_note"]
    assert any("NFET" in (e["data"].get("text") or "") for e in notes), notes
    rec = [e["data"] for e in events if e["event"] == "code_receipt"][-1]
    assert "nfet" in rec
    assert rec["nfet"].get("nfet_coding") is True
