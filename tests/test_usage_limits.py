# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Usage tiers + the shield — offline proofs (fake env, fake transport)."""
import hashlib
import json
import types

import pytest

from local_ui import usage_limits as ul

PW = "correct-horse"
PW_HASH = hashlib.sha256(PW.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _tmp_usage(tmp_path, monkeypatch):
    ul.init(tmp_path)
    monkeypatch.delenv("LOLM_ADMIN_PASS_SHA256", raising=False)
    monkeypatch.delenv("LOLM_SIGNING_SECRET", raising=False)
    yield


def _req(fwd=None, host="203.0.113.9", admin=None, license=None):
    headers = {}
    if fwd:
        headers["x-forwarded-for"] = fwd
    if admin:
        headers["x-lolm-admin"] = admin
    if license:
        headers["x-lolm-license"] = license
    return types.SimpleNamespace(headers=headers,
                                 client=types.SimpleNamespace(host=host))


# ── enforcement scope ────────────────────────────────────────────────────────

def test_local_installs_are_never_limited():
    assert ul.enforced() is False
    assert ul.check_request(_req(fwd="1.2.3.4"))["tier"] == "unlimited"


def test_loopback_is_never_limited_even_when_enforced(monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    q = ul.check_request(_req(host="127.0.0.1"))
    assert q["allowed"] and q["tier"] == "unlimited"   # the box's own scripts keep working


# ── the shield ───────────────────────────────────────────────────────────────

def test_admin_unlock_rejects_wrong_and_accepts_right(monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    assert ul.admin_unlock("wrong") is None
    tok = ul.admin_unlock(PW)
    assert tok and ul.is_admin(tok)
    assert not ul.is_admin(tok[:-2] + "zz")            # tampered signature dies


def test_admin_is_unlimited(monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    monkeypatch.setenv("LOLM_FREE_RUNS_PER_DAY", "1")
    tok = ul.admin_unlock(PW)
    for _ in range(5):
        q = ul.check_request(_req(fwd="1.2.3.4", admin=tok))
        assert q["allowed"] and q["tier"] == "admin"


# ── free tier counting ───────────────────────────────────────────────────────

def test_free_tier_counts_then_denies_with_upgrade_info(monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    monkeypatch.setenv("LOLM_FREE_RUNS_PER_DAY", "2")
    r = _req(fwd="1.2.3.4")
    assert ul.check_request(r)["allowed"]
    assert ul.check_request(r)["allowed"]
    q = ul.check_request(r)
    assert not q["allowed"] and q["tier"] == "free" and q["used"] == 2 and q["limit"] == 2
    assert "plus" in q["tiers"] and q["tiers"]["plus"]["usd"] == 7.99
    # a DIFFERENT visitor is unaffected
    assert ul.check_request(_req(fwd="5.6.7.8"))["allowed"]


def test_visual_budget_is_separate(monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    monkeypatch.setenv("LOLM_FREE_RUNS_PER_DAY", "1")
    r = _req(fwd="9.9.9.9")
    assert ul.check_request(r, "runs")["allowed"]
    assert not ul.check_request(r, "runs")["allowed"]
    assert ul.check_request(r, "visual")["allowed"]     # separate counter


def test_usage_status_peeks_without_consuming(monkeypatch):
    """Workspace chip / pricing poll must not burn the daily budget."""
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    monkeypatch.setenv("LOLM_FREE_RUNS_PER_DAY", "3")
    r = _req(fwd="10.0.0.5")
    s0 = ul.usage_status(r)
    assert s0["tier"] == "free"
    assert s0["runs"]["used"] == 0 and s0["runs"]["remaining"] == 3
    assert s0["unlimited"] is False
    # three peeks leave the counter untouched
    for _ in range(3):
        s = ul.usage_status(r)
        assert s["runs"]["used"] == 0 and s["runs"]["remaining"] == 3
    # real gated calls still count
    assert ul.check_request(r)["allowed"]
    s1 = ul.usage_status(r)
    assert s1["runs"]["used"] == 1 and s1["runs"]["remaining"] == 2
    assert s1["upgrade_hint"] is True   # free + remaining <= 3


def test_usage_status_unlimited_when_not_enforced():
    s = ul.usage_status(_req(fwd="1.2.3.4"))
    assert s["unlimited"] is True
    assert s["runs"]["remaining"] is None


# ── subscriber licenses ──────────────────────────────────────────────────────

def test_license_round_trip_and_higher_limits(monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    monkeypatch.setenv("LOLM_FREE_RUNS_PER_DAY", "1")
    lic = ul.mint_license("sub_123", "plus")
    parsed = ul.read_license(lic)
    assert parsed == {"sub_id": "sub_123", "tier": "plus"}
    assert ul.read_license(lic[:-2] + "zz") is None     # tamper
    r = _req(fwd="1.2.3.4", license=lic)
    for _ in range(3):                                   # beyond the free limit
        assert ul.check_request(r)["allowed"]
    assert ul.check_request(r)["tier"] == "plus"


# ── Stripe checkout + claim (fake transport) ────────────────────────────────

def test_checkout_builds_a_monthly_subscription(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    seen = {}

    class _R:
        status_code = 200
        def json(self):
            return {"url": "https://checkout.stripe.com/pay/cs_x"}

    import requests
    monkeypatch.setattr(requests, "post",
                        lambda url, data=None, auth=None, timeout=None:
                        (seen.update(url=url, data=data, auth=auth), _R())[1])
    out = ul.create_subscription_checkout("plus", "https://lolm.imagineqira.com/")
    assert out["url"].startswith("https://checkout.stripe.com/")
    assert seen["data"]["mode"] == "subscription"
    assert seen["data"]["line_items[0][price_data][recurring][interval]"] == "month"
    assert seen["data"]["line_items[0][price_data][unit_amount]"] == "799"
    assert "pricing.html?sub_session=" in seen["data"]["success_url"]
    assert "pricing.html?cancelled=1" in seen["data"]["cancel_url"]
    assert seen["auth"] == ("sk_test_x", "")


def test_claim_mints_license_only_for_live_paid_subs(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")

    def fake_get(url, params=None, auth=None, timeout=None):
        class _R:
            status_code = 200
            def json(self):
                return {"payment_status": "paid",
                        "subscription": {"id": "sub_ok", "status": "active",
                                         "metadata": {"tier": "pro"}}}
        return _R()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    out = ul.claim_subscription("cs_123")
    assert out["tier"] == "pro"
    assert ul.read_license(out["license"])["sub_id"] == "sub_ok"

    def fake_get_unpaid(url, params=None, auth=None, timeout=None):
        class _R:
            status_code = 200
            def json(self):
                return {"payment_status": "unpaid",
                        "subscription": {"id": "s", "status": "incomplete",
                                         "metadata": {"tier": "pro"}}}
        return _R()

    monkeypatch.setattr(requests, "get", fake_get_unpaid)
    assert "error" in ul.claim_subscription("cs_bad")   # no free rides
