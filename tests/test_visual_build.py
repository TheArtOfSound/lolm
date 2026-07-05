# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The self-verifying visual builder: it must RUN the game, and when a build is
broken it must feed the failure back and rebuild until a real browser confirms
it works — never claim success it hasn't seen."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import local_ui.code_routes as cr


def _sse_events(text: str):
    name = None
    for ln in text.splitlines():
        if ln.startswith("event: "):
            name = ln[7:]
        elif ln.startswith("data: ") and name:
            try:
                yield name, json.loads(ln[6:])
            except Exception:
                pass


DOC = "<!DOCTYPE html><html><body><canvas></canvas><script>/*{tag}*/</script></body></html>"


def test_verdict_score_prefers_more_working():
    better = {"renders": True, "animates": True, "responds": True, "console_errors": []}
    worse = {"renders": True, "animates": False, "responds": False, "console_errors": ["x"]}
    assert cr._verdict_score(better) > cr._verdict_score(worse)


def test_verify_html_degrades_gracefully_without_playwright(monkeypatch):
    # if the verifier subprocess can't run, we get working:None (ship, don't block)
    monkeypatch.setattr(cr.os.path, "exists", lambda p: False)
    v = cr._verify_html("<html></html>")
    assert v["working"] is None


def test_build_loop_retries_until_a_real_browser_confirms_it_works(monkeypatch):
    """attempt 1 renders BLANK -> the loop feeds the failure back -> attempt 2
    works and the browser confirms it. The receipt says verified only then."""
    calls = {"gen": 0, "verify": 0}

    def fake_chat(msgs, max_new_tokens=None):
        calls["gen"] += 1
        # the fix prompt must actually reach the model on retry
        if calls["gen"] >= 2:
            assert any("DID NOT WORK" in m["content"] for m in msgs)
        return DOC.format(tag=("broken" if calls["gen"] == 1 else "fixed"))

    def fake_verify(html, wait_ms=1400, timeout=55):
        calls["verify"] += 1
        if "broken" in html:
            return {"working": False, "renders": False, "animates": False,
                    "responds": False, "console_errors": [],
                    "reasons": ["the canvas is BLANK — only 1 colour drawn"]}
        return {"working": True, "renders": True, "animates": True,
                "responds": True, "console_errors": [], "reasons": []}

    monkeypatch.setattr(cr, "_verify_html", fake_verify)
    app = FastAPI()
    cr.register_code_routes(app, "/tmp/lolm_test_sb", fake_chat)
    client = TestClient(app)

    r = client.post("/api/demo/code/visual/build", json={"task": "build a maze game"})
    assert r.status_code == 200
    evs = list(_sse_events(r.text))
    verdicts = [d for n, d in evs if n == "verdict"]
    done = [d for n, d in evs if n == "done"][-1]

    assert len(verdicts) == 2                      # it retried after the broken build
    assert verdicts[0]["working"] is False and verdicts[1]["working"] is True
    assert done["verified"] is True                # only claims verified once the browser agreed
    assert "fixed" in done["html"]                 # shipped the WORKING candidate
    assert done["attempts"] == 2
    assert calls["gen"] == 2                        # regenerated exactly once


def test_build_loop_reports_honestly_when_it_cannot_fix(monkeypatch):
    """If it never works, it returns the best attempt and does NOT claim verified."""
    def fake_chat(msgs, max_new_tokens=None):
        return DOC.format(tag="stillbroken")

    def fake_verify(html, wait_ms=1400, timeout=55):
        return {"working": False, "renders": False, "animates": False, "responds": False,
                "console_errors": [], "reasons": ["frozen"]}

    monkeypatch.setattr(cr, "_verify_html", fake_verify)
    app = FastAPI()
    cr.register_code_routes(app, "/tmp/lolm_test_sb2", fake_chat)
    client = TestClient(app)

    r = client.post("/api/demo/code/visual/build", json={"task": "build something"})
    done = [d for n, d in _sse_events(r.text) if n == "done"][-1]
    assert done["verified"] is False               # honest — never falsely claims it works
    assert done["html"]                            # still returns the best effort
    assert done["attempts"] == 4                   # exhausted the retry budget
