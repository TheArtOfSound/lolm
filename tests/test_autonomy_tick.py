# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the autonomy tick loop + memory consolidation."""

from lolm.agent.autonomy_tick import autonomy_tick, TickInput
from lolm.agent.agent_state import (load_agent_state, AgentState, persist_agent_state,
                                     compute_autonomy_level, AutonomyLevel)
from lolm.control.memory_consolidation import (memory_write_score, retention_class,
                                               decide_memory_write)


def test_tick_idles_under_low_pressure_and_writes_receipt(tmp_path):
    out = autonomy_tick(TickInput("agentA", "scheduled_tick", liveStats={"memories": 10}),
                        base_dir=tmp_path)
    assert out["decision"]["mode"] == "idle"
    assert out["decision"]["actionTriggered"] is False
    assert out["receipt"]["receiptHash"]                       # idle still gets a receipt
    st = load_agent_state("agentA", tmp_path)
    assert st.ticksRun == 1 and st.lastReceiptHash == out["receipt"]["receiptHash"]


def test_tick_indicates_verify_but_does_not_fake_execution(tmp_path):
    # Seed state with high unresolved uncertainty + verification pressure.
    st = AgentState(agentId="agentB", unresolvedUncertainty=0.9,
                    verificationPressure=0.85, contradictionRisk=0.6)
    persist_agent_state(st, tmp_path)
    out = autonomy_tick(TickInput("agentB", "uncertainty_review_tick"), base_dir=tmp_path)
    assert out["decision"]["mode"] == "verify"
    act = out["receipt"]["actions"][0]
    # No runner wired -> indicated but NOT executed, recorded honestly.
    assert act["triggered"] is True and act["executed"] is False
    assert "not executed" in (act["blockedReason"] or "")
    assert out["receipt"]["controllerClaim"]["actionCount"] == 0  # nothing executed


def test_tick_hash_chains_across_ticks(tmp_path):
    a = autonomy_tick(TickInput("agentC", liveStats={"memories": 1}), base_dir=tmp_path)
    b = autonomy_tick(TickInput("agentC", liveStats={"memories": 2}), base_dir=tmp_path)
    assert b["receipt"]["previousReceiptHash"] == a["receipt"]["receiptHash"]
    assert b["receipt"]["receiptHash"] != a["receipt"]["receiptHash"]


def test_memory_write_score_and_retention():
    good = {"goalRelevance": 0.9, "futureUsefulness": 0.9, "userPreferenceImportance": 0.8,
            "factualStability": 0.9, "novelty": 0.7, "privacyRisk": 0.0, "duplicationPenalty": 0.0}
    d = decide_memory_write({**good, "text": "user prefers metric units"})
    assert d["written"] is True and d["retentionClass"] in ("project", "long_term", "session")

    private = {**good, "privacyRisk": 0.9, "text": "user SSN is ..."}
    dp = decide_memory_write(private)
    assert dp["written"] is False and dp["retentionClass"] == "do_not_store"

    junk = {"novelty": 0.1, "text": "ok"}
    dj = decide_memory_write(junk)
    assert dj["written"] is False and dj["retentionClass"] == "ephemeral"


def test_autonomy_level_is_honest():
    assert compute_autonomy_level({"receipts": True}) == AutonomyLevel.L1
    assert compute_autonomy_level({"receipts": True, "controller_actions": True}) == AutonomyLevel.L2
    assert compute_autonomy_level({"controller_actions": True, "memory_goal_ticks": True}) == AutonomyLevel.L3
    assert compute_autonomy_level({"memory_goal_ticks": True, "tools": True}) == AutonomyLevel.L4
    # No tools -> never claims L4 even with ticks.
    assert compute_autonomy_level({"memory_goal_ticks": True}) == AutonomyLevel.L3
