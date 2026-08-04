# Copyright (c) 2026 Qira LLC. All rights reserved.
"""API keys + webhook SSRF guards."""

from local_ui import api_keys, webhooks, usage_limits


def test_mint_and_read_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", "x" * 64)
    usage_limits.init(tmp_path)
    api_keys.init(tmp_path)
    out = api_keys.mint_api_key(tier="free", label="t", ip="1.2.3.4")
    assert out.get("api_key", "").startswith("lolm_")
    raw = out["api_key"]
    row = api_keys.read_api_key(raw)
    assert row and row["tier"] == "free" and row["key_id"] == out["key_id"]
    assert api_keys.read_api_key("lolm_dead_beef") is None


def test_api_key_identity_beats_ip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", "a" * 64)
    usage_limits.init(tmp_path)
    api_keys.init(tmp_path)
    out = api_keys.mint_api_key(tier="plus", label="p", ip="9.9.9.9")
    raw = out["api_key"]

    class R:
        headers = {"x-lolm-api-key": raw, "x-forwarded-for": "8.8.8.8"}
        client = type("C", (), {"host": "1.1.1.1"})()

    who = usage_limits._identity_and_tier(R())
    assert who["identity"].startswith("api:")
    assert who["tier"] == "plus"


def test_webhook_ssrf_blocks_private():
    assert webhooks.validate_webhook_url("http://127.0.0.1/hook")
    assert webhooks.validate_webhook_url("http://localhost/x")
    assert webhooks.validate_webhook_url("ftp://example.com/x")
    # public host should pass hostname check (may fail DNS in sandbox — accept None or dns fail)
    # example.com is public
    err = webhooks.validate_webhook_url("https://example.com/hook")
    assert err is None


def test_keys_route_mint_free(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", "b" * 64)
    usage_limits.init(tmp_path)
    api_keys.init(tmp_path)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from local_ui.integrate_routes import register_integrate_routes

    app = FastAPI()
    register_integrate_routes(app)
    c = TestClient(app)
    r = c.post("/api/demo/api-keys", json={"tier": "free", "label": "ci"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key"].startswith("lolm_")
    r2 = c.get("/api/demo/api-keys", headers={"X-LOLM-Api-Key": body["api_key"]})
    assert r2.status_code == 200
