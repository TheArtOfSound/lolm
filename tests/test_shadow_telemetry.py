# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Track 3 passive shadow router — never applies adaptive selection."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lolm.agent_capability_core import AgentCapabilityCore
from lolm.capability_router import ModelPerformance, TaskKind, TaskProfile
from lolm.shadow_telemetry import (
    ADAPTIVE_ROUTING_ENABLED,
    ActualOutcome,
    RoleSelection,
    ShadowRouter,
    adaptive_routing_active,
)


def test_adaptive_routing_hard_disabled():
    assert ADAPTIVE_ROUTING_ENABLED is False
    assert adaptive_routing_active() is False


def test_prepare_request_records_shadow_without_applying():
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "shadow.jsonl"
        shadow = ShadowRouter(log_path=log)
        core = AgentCapabilityCore(shadow=shadow)
        dec = core.prepare_request(
            "Fix the parser bug in this repository",
            has_repository=True,
            performance={
                ("x", "repo_edit:python"): ModelPerformance(
                    "x", "repo_edit:python", attempts=200, pass_rate=0.99,
                ),
            },
            persist_shadow=True,
        )
        assert dec.shadow is not None
        assert dec.shadow_route is not None
        assert dec.shadow.adaptive_routing_applied is False
        assert dec.to_dict()["adaptive_routing_applied"] is False
        # Live route is baseline (priors); shadow may differ once measured data exists
        assert dec.route.profile.bucket == dec.shadow.task_bucket
        assert log.exists()
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        assert "shadow_router_selection" in lines[0]


def test_apply_selection_always_baseline_when_passive():
    shadow = ShadowRouter()
    base = RoleSelection(planner="a", executor="b", verifier="c")
    sh = RoleSelection(planner="d", executor="b", verifier="e")
    used = shadow.apply_selection_for_live(base, sh)
    assert used == base


def test_complete_observation_retains_failures():
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "s.jsonl"
        shadow = ShadowRouter(log_path=log)
        profile = TaskProfile(kind=TaskKind.FACTUAL_QA, requires_retrieval=True)
        rec = shadow.open_observation(profile, run_id="t1")
        shadow.complete_observation(
            rec,
            ActualOutcome(
                verdict="failed",
                false_ship=False,
                unsupported_claims=2,
                terminal="failed",
            ),
        )
        assert rec.actual_outcome["terminal"] == "failed"
        assert rec.actual_outcome["unsupported_claims"] == 2
        # failures must be retained, not filtered
        assert any(r["actual_outcome"].get("terminal") == "failed" for r in shadow.recent())


def test_record_run_outcome_on_core():
    core = AgentCapabilityCore()
    dec = core.prepare_request("What is 2+2?", persist_shadow=False)
    completed = core.record_run_outcome(
        dec,
        verdict="verified_complete",
        unsupported_claims=0,
        latency_ms=12.5,
    )
    assert completed is not None
    assert completed.actual_outcome["verdict"] == "verified_complete"
    assert completed.adaptive_routing_applied is False
