# Copyright (c) 2026 Qira LLC. All rights reserved.
"""BYOK anti-rot matrix — every paid key must provably upgrade the flows it
claims to. These tests are offline (fake env, no network): they pin the
routing/selection logic so a key can never silently become decorative again."""
import os

# importing server_public_demo must NOT boot model-load/scheduler threads in tests
os.environ.setdefault("LOLM_TEST_NO_BOOT", "1")

import pytest

from local_ui.public_demo import DemoLimits, clamp_request


# ── Anti-rot guard: every key in the panel MUST have a real consumer ────────
# A spec without a probe here fails CI — that's the point: no key can ever
# become decorative again without this test screaming.

_CONSUMERS = {
    "ANTHROPIC_API_KEY": ("local_ui/server_public_demo.py", "local_ui/claude_reasoner.py"),
    "GROQ_API_KEY": ("local_ui/direct_providers.py",),
    "CEREBRAS_API_KEY": ("local_ui/direct_providers.py",),
    "OPENAI_API_KEY": ("local_ui/direct_providers.py",),
    "TOGETHER_API_KEY": ("local_ui/direct_providers.py",),
    "OPENROUTER_API_KEY": ("local_ui/direct_providers.py",),
    "WORKERS_AI_URL": ("local_ui/workers_ai_reasoner.py",),
    "WORKERS_AI_SECRET": ("local_ui/workers_ai_reasoner.py",),
    "LOLM_BRAIN": ("local_ui/server_public_demo.py",),
    "LOLM_LOCAL_MODEL": ("local_ui/local_brain.py",),
    "LOLM_LOCAL_URL": ("local_ui/local_brain.py",),
    "LOLM_LOCAL_API": ("local_ui/local_brain.py",),
    "LOLM_LOCAL_API_KEY": ("local_ui/local_brain.py",),
    "BRAVE_SEARCH_API_KEY": ("local_ui/internet_tools.py",),
    "TAVILY_API_KEY": ("local_ui/internet_tools.py",),
    "SEARXNG_URL": ("local_ui/internet_tools.py",),
}


def test_every_key_spec_has_a_real_consumer():
    from pathlib import Path
    from local_ui.byok import KEY_SPECS
    root = Path(__file__).resolve().parent.parent
    missing = []
    for spec in KEY_SPECS:
        env = spec["env"]
        files = _CONSUMERS.get(env)
        if not files:
            missing.append(f"{env}: no consumer registered in the anti-rot map")
            continue
        if not any(env in (root / f).read_text(encoding="utf-8") for f in files):
            missing.append(f"{env}: not actually read by {files}")
    assert not missing, "DECORATIVE KEYS (panel promises something nothing consumes):\n  " + "\n  ".join(missing)


def test_no_consumerless_additions_sneak_in():
    """The inverse guard: adding a KEY_SPECS entry without updating _CONSUMERS fails."""
    from local_ui.byok import KEY_SPECS
    unmapped = [s["env"] for s in KEY_SPECS if s["env"] not in _CONSUMERS]
    assert not unmapped, f"new specs missing an anti-rot consumer mapping: {unmapped}"


# ── Step 1: "auto" reasoner resolution ──────────────────────────────────────

def test_auto_reasoner_is_the_default(monkeypatch):
    monkeypatch.delenv("DEMO_REASONER", raising=False)
    assert DemoLimits().reasoner == "auto"


def test_explicit_reasoner_env_still_wins(monkeypatch):
    monkeypatch.setenv("DEMO_REASONER", "workers_ai")
    assert DemoLimits().reasoner == "workers_ai"


def test_clamp_request_resolves_auto(monkeypatch):
    monkeypatch.delenv("DEMO_REASONER", raising=False)
    limits = DemoLimits()
    # the route resolves auto via the injected resolver and passes it down:
    req = clamp_request("what is 2+2", limits, reasoner="claude")
    assert req.reasoner == "claude"
    # unresolved auto degrades to local honestly (no resolver wired)
    req2 = clamp_request("what is 2+2", limits)
    assert req2.reasoner == "local"


class _FakeGen:
    """Scripted brain: yields the given events, or raises."""
    def __init__(self, events=None, raise_exc=False):
        self.events, self.raise_exc = events or [], raise_exc
        self.calls = 0

    def __call__(self, req):
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("quota")
        yield from self.events


def _claude_first(claude, fallback, monkeypatch):
    import local_ui.server_public_demo as spd
    cf = spd._ClaudeFirst(claude, fallback)
    return cf


# ── Step 2: Claude error → cascade fallthrough ──────────────────────────────

@pytest.fixture()
def spd_mod():
    # importing server_public_demo boots the whole app once (heavy but cached)
    import local_ui.server_public_demo as spd
    return spd


def test_claude_error_falls_through_to_cascade(spd_mod, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    monkeypatch.delenv("LOLM_SOVEREIGN", raising=False)
    claude = _FakeGen(raise_exc=True)
    fallback = _FakeGen(events=[{"event": "token", "data": {"token": "4"}},
                                {"event": "done", "data": {"response": "4"}}])
    cf = spd_mod._ClaudeFirst(claude, fallback)
    events = list(cf({"q": "2+2"}))
    kinds = [e["event"] for e in events]
    assert "done" in kinds                          # the fallback actually answered
    assert any(e["event"] == "phase" and e["data"].get("phase") == "brain_fallback"
               for e in events)                     # honestly labelled
    assert fallback.calls == 1


def test_claude_error_event_before_tokens_falls_through(spd_mod, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    claude = _FakeGen(events=[{"event": "error", "data": {"error": "429 rate limited"}}])
    fallback = _FakeGen(events=[{"event": "done", "data": {"response": "ok"}}])
    cf = spd_mod._ClaudeFirst(claude, fallback)
    events = list(cf({}))
    assert any(e["event"] == "done" for e in events)
    assert fallback.calls == 1


def test_claude_success_never_touches_fallback(spd_mod, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    monkeypatch.delenv("LOLM_SOVEREIGN", raising=False)
    claude = _FakeGen(events=[{"event": "token", "data": {"token": "hi"}},
                              {"event": "done", "data": {"response": "hi"}}])
    fallback = _FakeGen(events=[{"event": "done", "data": {"response": "x"}}])
    cf = spd_mod._ClaudeFirst(claude, fallback)
    events = list(cf({}))
    assert [e["event"] for e in events] == ["token", "done"]
    assert fallback.calls == 0


# ── Step 3: hot-apply — a saved key flips availability WITHOUT reconstruction ──

def test_workers_ai_hot_applies_env(monkeypatch):
    from local_ui.workers_ai_reasoner import WorkersAIReasonerLoop
    monkeypatch.delenv("WORKERS_AI_URL", raising=False)
    monkeypatch.delenv("WORKERS_AI_SECRET", raising=False)
    loop = WorkersAIReasonerLoop(state_fn=lambda: None)     # constructed with NO keys
    assert loop.available() is False
    monkeypatch.setenv("WORKERS_AI_URL", "http://w/ai/generate")
    monkeypatch.setenv("WORKERS_AI_SECRET", "s")
    assert loop.available() is True                          # same object, keys applied live
    assert loop.url.endswith("/ai/generate")


def test_workers_ai_ctor_override_beats_env(monkeypatch):
    from local_ui.workers_ai_reasoner import WorkersAIReasonerLoop
    monkeypatch.setenv("WORKERS_AI_URL", "http://env")
    loop = WorkersAIReasonerLoop(state_fn=lambda: None, url="http://ctor", secret="x")
    assert loop.url == "http://ctor"                         # tests keep control


def test_local_brain_hot_applies_and_reprobes(monkeypatch):
    from local_ui import local_brain as lb
    monkeypatch.delenv("LOLM_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("LOLM_LOCAL_URL", raising=False)
    monkeypatch.delenv("LOLM_LOCAL_API", raising=False)
    # Isolate from a live evolved serve on the developer machine.
    monkeypatch.setattr(lb, "probe_evolved", lambda *a, **k: False)
    loop = lb.LocalServerReasonerLoop(state_fn=lambda: None)
    assert loop.configured() is False
    monkeypatch.setenv("LOLM_LOCAL_MODEL", "qwen2.5:3b")
    assert loop.configured() is True                         # env applied live
    # config change invalidates the health cache (no stale 30s verdict)
    loop._healthy, loop._health_cfg = True, ("old", "cfg", "x")
    monkeypatch.setattr(loop, "_probe_ok", lambda: False, raising=False)
    # available() sees cfg != cached cfg → resets _healthy before using it
    monkeypatch.setenv("LOLM_LOCAL_URL", "http://127.0.0.1:9")   # unreachable
    assert loop.available() is False


def test_evolved_auto_discovers_when_local_env_unset(monkeypatch):
    """No LOLM_LOCAL_* → pick lolm-evolved on :11435 when the probe is live."""
    from local_ui import local_brain as lb
    for k in ("LOLM_LOCAL_MODEL", "LOLM_LOCAL_URL", "LOLM_LOCAL_API", "LOLM_EVOLVED_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(lb, "probe_evolved", lambda *a, **k: True)
    loop = lb.LocalServerReasonerLoop(state_fn=lambda: None)
    assert loop.configured() is True
    assert loop.source() == "evolved_auto"
    assert loop.model == "lolm-evolved"
    assert loop.api == "openai"
    assert "11435" in loop.url
    assert loop.available() is True


def test_explicit_local_env_beats_evolved_auto(monkeypatch):
    from local_ui import local_brain as lb
    monkeypatch.setenv("LOLM_LOCAL_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("LOLM_LOCAL_URL", "http://127.0.0.1:11434")
    monkeypatch.delenv("LOLM_LOCAL_API", raising=False)
    monkeypatch.setattr(lb, "probe_evolved", lambda *a, **k: True)
    loop = lb.LocalServerReasonerLoop(state_fn=lambda: None)
    assert loop.source() == "env"
    assert loop.model == "qwen2.5:7b"
    assert loop.api == "ollama"


def test_bestbrain_uses_evolved_as_rescue_after_cloud(monkeypatch):
    """Auto-evolved must NOT demote Workers/direct — cloud first, evolved rescue."""
    from local_ui.local_brain import BestBrain

    class _Local:
        def available(self): return True
        def source(self): return "evolved_auto"
        def __call__(self, req):
            yield {"event": "token", "data": {"token": "evolved "}}
            yield {"event": "done", "data": {"response": "evolved ok"}}

    class _Cloud:
        def __init__(self, fail=False):
            self.fail, self.calls = fail, 0
        def available(self): return True
        def __call__(self, req):
            self.calls += 1
            if self.fail:
                yield {"event": "error", "data": {"error": "workers 429"}}
                return
            yield {"event": "token", "data": {"token": "cloud "}}
            yield {"event": "done", "data": {"response": "cloud ok"}}

    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    monkeypatch.delenv("LOLM_SOVEREIGN", raising=False)

    cloud_ok = _Cloud(fail=False)
    bb = BestBrain(_Local(), cloud_ok)
    assert bb.active() == "cloud"
    events = list(bb({}))
    assert any(e["event"] == "done" and "cloud" in e["data"].get("response", "") for e in events)

    cloud_bad = _Cloud(fail=True)
    bb2 = BestBrain(_Local(), cloud_bad)
    events2 = list(bb2({}))
    kinds = [e["event"] for e in events2]
    assert "phase" in kinds
    assert any(e.get("data", {}).get("phase") == "brain_fallback" for e in events2)
    assert any(e["event"] == "done" and "evolved" in e["data"].get("response", "") for e in events2)


def test_bestbrain_explicit_local_still_leads(monkeypatch):
    from local_ui.local_brain import BestBrain

    class _Local:
        def available(self): return True
        def source(self): return "env"
        def __call__(self, req):
            yield {"event": "done", "data": {"response": "local ok"}}

    class _Cloud:
        def available(self): return True
        def __call__(self, req):
            yield {"event": "done", "data": {"response": "cloud ok"}}

    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    monkeypatch.delenv("LOLM_SOVEREIGN", raising=False)
    bb = BestBrain(_Local(), _Cloud())
    assert bb.active() == "local"
    assert list(bb({}))[0]["data"]["response"] == "local ok"


def test_resolver_prefers_claude_then_cascade(spd_mod, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    monkeypatch.delenv("LOLM_SOVEREIGN", raising=False)
    assert spd_mod._resolve_reasoner() == "claude"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resolved = spd_mod._resolve_reasoner()
    assert resolved in ("workers_ai", "local")      # cascade if configured, else local


# ── Step 4: direct providers — YOUR OWN key works with no gateway ────────────

_DP_KEYS = ("GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENAI_API_KEY",
            "TOGETHER_API_KEY", "OPENROUTER_API_KEY")


def _clear_dp(monkeypatch):
    for k in _DP_KEYS + ("LOLM_SOVEREIGN", "WORKERS_AI_URL", "WORKERS_AI_SECRET"):
        monkeypatch.delenv(k, raising=False)


def test_direct_provider_key_flips_availability_live(monkeypatch):
    import local_ui.direct_providers as dp
    _clear_dp(monkeypatch)
    loop = dp.DirectProviderLoop(state_fn=lambda: None)
    assert loop.available() is False
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    assert loop.available() is True                  # hot-apply, no reconstruction
    assert loop.active_provider() == "groq"


def test_sovereign_refuses_direct_providers(monkeypatch):
    import local_ui.direct_providers as dp
    _clear_dp(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("LOLM_SOVEREIGN", "1")
    assert dp.configured() == []                     # sovereign means sovereign


def test_direct_generate_sends_bearer_to_right_endpoint(monkeypatch):
    import local_ui.direct_providers as dp
    _clear_dp(monkeypatch)
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test")
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            import json as _j
            return _j.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        return _Resp()

    monkeypatch.setattr(dp.urllib.request, "urlopen", fake_urlopen)
    loop = dp.DirectProviderLoop(state_fn=lambda: None)

    class _Req:
        max_new_tokens = 64
        messages = []
        telemeter = False
    r = loop._generate(_Req())
    assert r["provider"] == "cerebras-direct" and r["text"] == "hi"
    assert "api.cerebras.ai" in seen["url"]
    assert seen["auth"] == "Bearer csk-test"


def test_direct_generate_many_maps_cascade_ids(monkeypatch):
    import local_ui.direct_providers as dp
    _clear_dp(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    calls = []

    def fake_chat_once(p, model, messages, max_tokens, timeout):
        calls.append((p["name"], model))
        return f"answer from {model}"

    monkeypatch.setattr(dp, "_chat_once", fake_chat_once)
    loop = dp.DirectProviderLoop(state_fn=lambda: None)
    cands = loop.generate_many([{"role": "user", "content": "x"}],
                               ["zai-glm-4.7", "openai/gpt-oss-120b",
                                "meta-llama/llama-4-scout-17b-16e-instruct"])
    provs = sorted(c["provider"] for c in cands)
    assert provs == ["cerebras-direct", "groq-direct", "groq-direct"]
    assert all(c.get("text") for c in cands)


# ── Step 5: streaming backend picker + Claude ensemble candidate ─────────────

def test_stream_backend_prefers_claude_then_worker_then_direct(spd_mod, monkeypatch):
    _clear_dp(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    assert spd_mod._stream_backend() is spd_mod.CLAUDE
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("WORKERS_AI_URL", "http://w")
    monkeypatch.setenv("WORKERS_AI_SECRET", "s")
    assert spd_mod._stream_backend() is spd_mod.FRONTIER
    monkeypatch.delenv("WORKERS_AI_URL", raising=False)
    monkeypatch.delenv("WORKERS_AI_SECRET", raising=False)
    assert spd_mod._stream_backend() is spd_mod.DIRECT


# ── Step 6: utility tier — background turns never bill the Claude key ────────

def test_utility_purpose_skips_claude(spd_mod, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    monkeypatch.delenv("LOLM_SOVEREIGN", raising=False)
    calls = {"claude": 0, "fallback": 0}

    def fake_claude(req):
        calls["claude"] += 1
        yield {"event": "done", "data": {"response": "claude says"}}

    class _FB:
        def available(self):
            return True
        def __call__(self, req):
            calls["fallback"] += 1
            yield {"event": "done", "data": {"response": "cascade says"}}

    monkeypatch.setattr(spd_mod.GEN, "claude", fake_claude)
    monkeypatch.setattr(spd_mod.GEN, "fallback", _FB())
    out_util = spd_mod._operator_chat([{"role": "user", "content": "tick"}], purpose="utility")
    assert out_util == "cascade says" and calls["claude"] == 0   # never billed
    out_ans = spd_mod._operator_chat([{"role": "user", "content": "code this"}])
    assert out_ans == "claude says" and calls["claude"] == 1     # quality turns still claude


def test_ensemble_gains_a_claude_candidate_when_key_set(spd_mod, monkeypatch):
    _clear_dp(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LOLM_BRAIN", raising=False)
    monkeypatch.setattr(spd_mod.CLOUD, "generate_many",
                        lambda m, mods, mt=3600: [{"model": "x", "provider": "groq", "text": "a"}])
    monkeypatch.setattr(spd_mod, "_operator_chat",
                        lambda msgs, max_new_tokens=640: "claude's build")
    cands = spd_mod._operator_gen_many([{"role": "user", "content": "x"}], ["x"])
    provs = [c["provider"] for c in cands]
    assert "anthropic" in provs                      # claude joined the race
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cands2 = spd_mod._operator_gen_many([{"role": "user", "content": "x"}], ["x"])
    assert all(c["provider"] != "anthropic" for c in cands2)
