# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the gated action runtime (network-free)."""

from lolm.autonomy import AutonomyGate, ACT, ESCALATE
from lolm.calibration import UncertaintyCalibrator
from local_ui.operator import (
    Operator, SandboxPyTool, ShellReadTool, WebReadTool, Tool, Observation,
)


def _confident_gate():
    us, ys = [], []
    for u in [0.0, 0.3, 0.8, 1.5, 2.5]:
        us += [u] * 40
        k = round(40 * max(0.0, 1 - u / 3.2))
        ys += [1] * k + [0] * (40 - k)
    return AutonomyGate(UncertaintyCalibrator().fit(us, ys))


def test_sandbox_runs_and_verifies_correct_code():
    op = Operator(_confident_gate())
    rec = op.attempt("run_python", {"code": "print(6*7)"}, uncertainty=0.2)
    assert rec.executed and rec.outcome == "verified"
    assert "42" in rec.observation["data"]["stdout"]


def test_sandbox_marks_failing_code_failed_not_verified():
    op = Operator(_confident_gate())
    rec = op.attempt("run_python", {"code": "raise SystemExit(3)"}, uncertainty=0.2)
    assert rec.executed and rec.outcome == "failed"


def test_high_uncertainty_does_not_execute():
    op = Operator(_confident_gate())
    # run_code is reversible; very high uncertainty must NOT run it.
    rec = op.attempt("run_python", {"code": "print(1)"}, uncertainty=2.5)
    assert rec.executed is False and rec.outcome in ("escalate", "gather")


def test_shell_read_whitelist_blocks_writes():
    op = Operator(_confident_gate())
    # The gate ACTs (read tier, low U), but the tool itself refuses non-read cmds.
    rec = op.attempt("shell_read", {"cmd": "rm -rf /tmp/x"}, uncertainty=0.1)
    assert rec.executed and rec.outcome == "failed"
    assert "whitelist" in rec.observation["detail"]
    # Metacharacters are refused too.
    rec2 = op.attempt("shell_read", {"cmd": "ls; rm -rf /"}, uncertainty=0.1)
    assert rec2.outcome == "failed" and "metacharacter" in rec2.observation["detail"]


def test_shell_read_allows_readonly():
    op = Operator(_confident_gate())
    rec = op.attempt("shell_read", {"cmd": "date"}, uncertainty=0.1)
    assert rec.executed and rec.outcome == "verified"


def test_web_read_rejects_non_http_scheme_without_network():
    op = Operator(_confident_gate())
    rec = op.attempt("web_read", {"url": "ftp://example.com/x"}, uncertainty=0.1)
    assert rec.executed and rec.outcome == "failed"


def test_hard_gated_tool_never_executes_even_when_certain():
    class DeployTool(Tool):
        name = "deploy"
        action_kind = "deploy"   # in HARD_HUMAN_GATE
        def run(self, args):  # pragma: no cover - must never be called
            raise AssertionError("hard-gated tool must not execute")

    op = Operator(_confident_gate(), tools=[DeployTool()])
    rec = op.attempt("deploy", {"target": "prod"}, uncertainty=0.0)  # 'certain'
    assert rec.executed is False and rec.outcome == ESCALATE
    assert "hard-gated" in rec.decision["reason"]


def test_money_floor_escalates_code_action():
    op = Operator(_confident_gate())
    # A reversible code run, but the prompt is financial -> floor lifts the tier
    # and a modestly-uncertain run escalates instead of executing.
    rec = op.attempt("run_python", {"code": "print(1)"}, uncertainty=0.8,
                     risk_profiles=["financial"])
    assert rec.executed is False
