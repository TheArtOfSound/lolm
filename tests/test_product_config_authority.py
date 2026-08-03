from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def config():
    return json.loads((SITE / "product-config.json").read_text(encoding="utf-8"))


def test_canonical_product_config_has_expected_public_contract():
    cfg = config()
    assert cfg["schema"] == "lolm.product.v1"
    assert cfg["brand"]["product"] == "LOLM"
    assert cfg["brand"]["company"] == "Qira LLC"
    assert cfg["routes"]["app"] == "/app.html"
    assert cfg["routes"]["demo"] == "/try.html"
    assert cfg["packages"]["cli"] == "lolm-cli"
    assert cfg["packages"]["cli_install"] == "npm install -g lolm-cli"
    assert cfg["model"]["fixed_generator"] is False
    assert cfg["maturity"]["adaptive_routing"] is False
    assert cfg["maturity"]["track2b_competence"] == "not_proven"
    assert cfg["maturity"]["production_release"] == "blocked"


def test_plan_values_match_backend_authority():
    from local_ui.usage_limits import PLAN_LIMITS

    cfg = config()
    for name in ("free", "plus", "pro"):
        public = cfg["plans"][name]
        backend = PLAN_LIMITS[name]
        assert public["daily_runs"] == backend.runs
        assert public["daily_builds"] == backend.visual
        assert public["price_usd"] == backend.price_cents / 100


def test_pages_load_shared_product_config_and_use_canonical_plan_values():
    cfg = config()
    for filename in ("index.html", "pricing.html", "app.html"):
        text = (SITE / filename).read_text(encoding="utf-8")
        assert "/product-config.js" in text, filename
        assert "window.LOLM_PRODUCT" in text, filename

    pricing = (SITE / "pricing.html").read_text(encoding="utf-8")
    assert 'data-plan="free"' in pricing
    assert 'data-plan="plus"' in pricing
    assert 'data-plan="pro"' in pricing
    for name in ("free", "plus", "pro"):
        plan = cfg["plans"][name]
        assert str(plan["daily_runs"]) in pricing or "fillPlan" in pricing
        assert str(plan["daily_builds"]) in pricing or "fillPlan" in pricing


def test_no_stale_marketing_prices_remain_in_primary_site_pages():
    # Historical conflicts seen live: $9/120/20 and $19/500/60.
    stale = [
        re.compile(r"\$9(?:\.00)?\b"),
        re.compile(r"\b120\s+(?:agent\s+)?runs"),
        re.compile(r"\b500\s+(?:agent\s+)?runs"),
        re.compile(r"\b60\s+(?:verified\s+)?builds"),
        re.compile(r"\b8\s+runs(?:\s*/\s*day)?"),
    ]
    offenders = []
    for path in SITE.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        for rx in stale:
            if rx.search(text):
                offenders.append(f"{path.relative_to(ROOT)}:{rx.pattern}")
                break
    assert not offenders, "stale marketing prices:\n" + "\n".join(offenders[:40])


def test_pricing_page_does_not_use_admin_header_or_innerhtml_for_usage():
    html = (SITE / "pricing.html").read_text(encoding="utf-8")
    assert "lolm_admin" not in html
    assert "X-LOLM-Admin" not in html
    # claim must use GET session_id (backend contract)
    assert "billing/claim?session_id=" in html
    assert "method:'POST'" not in html or "billing/claim" not in html.split("method:'POST'")[0][-80:]
    # top-up checkout must not be active while routes 404
    assert "buyTopup" not in html
    assert "billing/topup/checkout" not in html
    # usage rendering should prefer textContent / createElement, not innerHTML for API
    # (allow other pages; lock pricing page)
    assert "text.innerHTML" not in html


def test_sw_cache_bumped_and_product_config_network_first():
    sw = (SITE / "sw.js").read_text(encoding="utf-8")
    assert "lolm-v20-artifact-delivery" in sw
    assert "product-config.json" in sw
    assert 'url.pathname === "/product-config.json"' in sw
    assert "fetch(event.request)" in sw
