# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The Workers-AI request must not balloon a big visual build past what a provider
can finish in the timeout window (the bug that dumped big builds onto the CPU model)."""
import json
import types

import local_ui.workers_ai_reasoner as war


class _Msg:
    def __init__(self, role, content):
        self.role, self.content = role, content


class _Req:
    def __init__(self, n):
        self.max_new_tokens = n
        self.messages = [_Msg("system", "sys"), _Msg("user", "make a game")]


def _capture(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"text": "ok", "provider": "groq"}).encode()

    def fake_urlopen(request, timeout=None):
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(war.urllib.request, "urlopen", fake_urlopen)
    return captured


def _loop():
    return war.WorkersAIReasonerLoop(state_fn=lambda: None, url="http://x", secret="s")


def test_big_visual_request_is_capped(monkeypatch):
    captured = _capture(monkeypatch)
    _loop()._generate(_Req(3600))                         # the visual builder's ask
    # 8192, NOT 10800 (3600*3): capped, but with room for the big cascade brains'
    # internal reasoning tokens so large HTML builds aren't truncated mid-file.
    assert captured["payload"]["max_tokens"] == 8192
    assert 100 < captured["timeout"] <= 150               # scaled up for a big gen, bounded


def test_small_planner_request_unchanged(monkeypatch):
    captured = _capture(monkeypatch)
    _loop()._generate(_Req(128))
    assert captured["payload"]["max_tokens"] == 384        # 128*3, still under the cap
    assert 30 <= captured["timeout"] < 45                  # ~30 + 384/40
