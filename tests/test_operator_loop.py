# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the autonomous operator loop (deterministic planner, no model)."""

from lolm.autonomy import AutonomyGate
from lolm.calibration import UncertaintyCalibrator
from lolm.flywheel import AutonomyFlywheel
from local_ui.operator import Operator, Tool, Observation
from local_ui.operator_loop import OperatorAgent


def _gate():
    us, ys = [], []
    for u in [0.0, 0.3, 0.8, 1.5, 2.5]:
        us += [u] * 40
        k = round(40 * max(0.0, 1 - u / 3.2))
        ys += [1] * k + [0] * (40 - k)
    return AutonomyGate(UncertaintyCalibrator().fit(us, ys))


def _scripted(plans):
    seq = list(plans)
    def planner(goal, history):
        return seq.pop(0) if seq else {"action": "finish", "answer": "done"}
    return planner


def test_loop_acts_then_finishes(tmp_path):
    fw = AutonomyFlywheel(tmp_path / "fw.jsonl", min_fit=1)
    agent = OperatorAgent(
        operator=Operator(_gate()),
        planner=_scripted([
            {"action": "tool", "tool": "run_python", "args": {"code": "print(6*7)"},
             "reason": "compute"},
            {"action": "finish", "answer": "42"},
        ]),
        flywheel=fw,
        uncertainty_fn=lambda _t: 0.2,
    )
    out = agent.run("compute 6*7")
    assert out["ended"] == "finished" and out["answer"] == "42"
    tool_steps = [s for s in out["steps"] if s.get("record")]
    assert tool_steps and tool_steps[0]["record"]["outcome"] == "verified"
    assert fw.count == 1   # the verified action fed the flywheel


def test_loop_escalates_and_stops_on_high_uncertainty():
    agent = OperatorAgent(
        operator=Operator(_gate()),
        planner=_scripted([
            {"action": "tool", "tool": "run_python", "args": {"code": "print(1)"},
             "reason": "risky"},
            {"action": "tool", "tool": "run_python", "args": {"code": "print(2)"},
             "reason": "should never run"},
        ]),
        uncertainty_fn=lambda _t: 2.5,   # too unsure
    )
    out = agent.run("do something")
    assert out["ended"] == "escalated_to_human"
    assert out["escalation"] and out["escalation"]["preview"].startswith("prepared but NOT")
    assert out["n_steps"] == 1           # stopped at the escalation, never ran step 2


def test_loop_respects_step_budget():
    agent = OperatorAgent(
        operator=Operator(_gate()),
        planner=lambda g, h: {"action": "tool", "tool": "run_python",
                              "args": {"code": "print(1)"}, "reason": "loop"},
        uncertainty_fn=lambda _t: 0.2,
        max_steps=3,
    )
    out = agent.run("infinite")
    assert out["ended"] == "step_budget" and out["n_steps"] == 3


def test_loop_unknown_tool_stops_honestly():
    agent = OperatorAgent(
        operator=Operator(_gate()),
        planner=_scripted([{"action": "tool", "tool": "nope", "args": {}}]),
        uncertainty_fn=lambda _t: 0.1,
    )
    out = agent.run("x")
    assert out["ended"] == "unknown_tool"


def test_loop_hard_gates_dangerous_tool_even_when_certain():
    class DeployTool(Tool):
        name = "deploy"
        action_kind = "deploy"
        def run(self, args):  # pragma: no cover
            raise AssertionError("must not execute")

    agent = OperatorAgent(
        operator=Operator(_gate(), tools=[DeployTool()]),
        planner=_scripted([{"action": "tool", "tool": "deploy",
                            "args": {"target": "prod"}, "reason": "ship it"}]),
        uncertainty_fn=lambda _t: 0.0,   # 'certain'
    )
    out = agent.run("deploy prod")
    assert out["ended"] == "escalated_to_human"
    assert out["steps"][0]["record"]["executed"] is False
