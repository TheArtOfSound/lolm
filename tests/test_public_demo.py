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


def test_demo_busy_lock(tmp_path):
    app, gate = make_app(tmp_path)
    client = TestClient(app)
    gate.lock.acquire()
    try:
        resp = client.post("/api/demo/run/stream", json={"command": "explain lolm"})
        assert resp.status_code == 429
        assert "in progress" in resp.json()["error"]
    finally:
        gate.lock.release()


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
