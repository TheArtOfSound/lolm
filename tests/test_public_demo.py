from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from local_ui.public_demo import DemoLimits, register_demo_routes
from tests.test_nfet_agent import FakeLoop, make_agent, segment_spec


def make_app(tmp_path, *, segments=None, model_ready=True, rate_per_hour=2):
    loop = FakeLoop(segments=segments or [
        segment_spec([3.0] * 28, "steady segment one"),
        segment_spec([3.0] * 28, "steady segment two", eos=True),
    ])
    agent, _ = make_agent(tmp_path, loop)
    app = FastAPI()
    replays = tmp_path / "replays"
    replays.mkdir()
    (replays / "index.json").write_text(json.dumps({
        "replays": [{"id": "gate-demo", "title": "Explain the gate", "command": "explain the gate"}]
    }))
    (replays / "gate-demo.json").write_text(json.dumps({
        "meta": {"id": "gate-demo", "command": "explain the gate"},
        "events": [{"event": "run_start", "data": {"command": "explain the gate"}},
                   {"event": "run_done", "data": {"ended_by": "nfet_finalize"}}],
    }))
    limits = DemoLimits()
    limits.rate_per_hour = rate_per_hour
    limits.max_segments = 2
    limits.segment_tokens = 28
    gate = register_demo_routes(app, agent, replays, limits,
                                model_ready_fn=lambda: model_ready)
    return app, gate


def parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append({"event": name, "data": data})
    return events


def test_demo_stream_runs_clamped(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    resp = client.post("/api/demo/run/stream",
                       json={"command": "explain lolm", "max_segments": 99})
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    names = [e["event"] for e in events]
    assert names[0] == "run_start" and names[-1] == "run_done"
    # clamped to demo limits regardless of client input
    assert events[0]["data"]["max_segments"] == 2
    assert events[0]["data"]["segment_tokens"] == 28
    done = events[-1]["data"]
    assert done["counters"]["segments"] <= 2


def test_demo_rate_limit(tmp_path):
    app, _ = make_app(tmp_path, rate_per_hour=1)
    client = TestClient(app)
    first = client.post("/api/demo/run/stream", json={"command": "explain lolm"})
    assert first.status_code == 200
    second = client.post("/api/demo/run/stream", json={"command": "explain lolm"})
    assert second.status_code == 429
    assert "rate limit" in second.json()["error"]


def test_demo_busy_lease(tmp_path):
    app, gate = make_app(tmp_path)
    client = TestClient(app)
    assert gate.try_acquire()
    try:
        resp = client.post("/api/demo/run/stream", json={"command": "explain lolm"})
        assert resp.status_code == 429
        assert "in progress" in resp.json()["error"]
        assert client.get("/api/demo/status").json()["busy"] is True
    finally:
        gate.release()
    assert client.get("/api/demo/status").json()["busy"] is False


def test_demo_stale_lease_self_heals(tmp_path):
    """A vanished client whose generator never ran must not lock the demo forever."""
    app, gate = make_app(tmp_path)
    client = TestClient(app)
    assert gate.try_acquire()
    # simulate a run that leaked its lease 10 minutes ago
    gate._lease_since = __import__("time").time() - 600
    assert client.get("/api/demo/status").json()["busy"] is False
    resp = client.post("/api/demo/run/stream", json={"command": "explain lolm"})
    assert resp.status_code == 200  # stale lease was taken over
    events = parse_sse(resp.text)
    assert events[-1]["event"] == "run_done"


def test_demo_model_not_ready(tmp_path):
    app, _ = make_app(tmp_path, model_ready=False)
    client = TestClient(app)
    resp = client.post("/api/demo/run/stream", json={"command": "explain lolm"})
    assert resp.status_code == 503


def test_demo_replays_and_status(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    listing = client.get("/api/demo/replays").json()
    assert listing["replays"][0]["id"] == "gate-demo"
    replay = client.get("/api/demo/replay/gate-demo").json()
    assert replay["events"][-1]["event"] == "run_done"
    assert client.get("/api/demo/replay/nope").status_code == 404
    # path traversal attempts are sanitized, not served
    assert client.get("/api/demo/replay/..%2Findex").status_code == 404
    status = client.get("/api/demo/status").json()
    assert status["model_ready"] is True
    assert status["replays"] == 1
    assert "limits" in status


def test_demo_empty_command(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.post("/api/demo/run/stream", json={"command": "  "}).status_code == 400


def test_demo_stats_durable_from_log(tmp_path):
    import json as _json
    log = tmp_path / "improvement_log.jsonl"
    rows = [
        {"type": "nfet_agent_run", "timestamp": __import__("time").time(),
         "proof": {"verdict": "nfet_control_visible",
                   "control_counts": {"retrieve": 1, "continue": 2},
                   "decision_sources": {"head": 2, "heuristic": 1}}},
        {"type": "nfet_agent_run", "timestamp": 1000.0,
         "proof": {"verdict": "changed_but_controls_quiet",
                   "control_counts": {"continue": 3},
                   "decision_sources": {"heuristic": 3}}},
        {"type": "chat"},
    ]
    log.write_text("\n".join(_json.dumps(r) for r in rows))

    from local_ui.public_demo import load_run_stats
    stats = load_run_stats(log)
    assert stats["total_runs"] == 2
    assert stats["runs_24h"] == 1
    assert stats["control_visible_runs"] == 1
    assert stats["controls"]["retrieve"] == 1
    assert stats["head_decisions"] == 2
    # cache: same key returns same object without reparse
    assert load_run_stats(log) is stats


def test_demo_stats_route(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    stats = client.get("/api/demo/stats").json()
    assert stats["total_runs"] == 0  # no log configured in test app
