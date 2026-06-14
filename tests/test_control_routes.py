# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the NFET control HTTP surface (read-only decide + system-state)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from local_ui.control_routes import register_control_routes


def _client():
    app = FastAPI()
    register_control_routes(app, agent_id="test-route-agent",
                            live_stats_fn=lambda: {"memories": 103, "turns": 44},
                            goals_fn=lambda st: [])
    return TestClient(app)


def test_decide_route_returns_packet():
    c = _client()
    r = c.post("/api/demo/control/decide",
               json={"signals": {"uncertainty": 0.87, "verificationNeed": 0.8,
                                 "contradictionRisk": 0.6}})
    assert r.status_code == 200
    d = r.json()
    assert d["selectedAction"] == "verify" and d["actionTriggered"] is True
    assert "fieldEnergy" in d["nfet"] and d["nfet"]["weights"]["fusion"]


def test_system_state_route_is_deterministic():
    c = _client()
    r = c.post("/api/demo/system-state",
               json={"question": "why do memory stats differ from /brain/stats?"})
    assert r.status_code == 200
    a = r.json()
    assert a["source"] == "metadata"
    assert "live" in a["answer"].lower()
    assert "may be a layer" not in a["answer"].lower()  # not speculation


def test_system_state_passes_through_non_state_questions():
    c = _client()
    r = c.post("/api/demo/system-state", json={"question": "capital of France?"})
    assert r.json()["answer"] is None
