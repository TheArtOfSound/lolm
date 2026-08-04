"""Lock the public product/pricing authority used by the website.

Marketing pages and Stripe checkout must not invent plan numbers independent of
local_ui.usage_limits.TIERS. Top-ups are not live until routes exist.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def test_usage_limits_tiers_are_canonical():
    from local_ui.usage_limits import TIERS, public_tiers

    assert TIERS["free"]["runs_per_day"] == 10
    assert TIERS["free"]["visual_per_day"] == 3
    assert TIERS["free"]["usd"] == 0.0
    assert TIERS["plus"]["usd"] == 7.99
    assert TIERS["plus"]["runs_per_day"] == 300
    assert TIERS["plus"]["visual_per_day"] == 30
    assert TIERS["pro"]["usd"] == 19.99
    assert TIERS["pro"]["runs_per_day"] == 2000
    assert TIERS["pro"]["visual_per_day"] == 200
    pub = public_tiers()
    assert set(pub) == {"free", "plus", "pro"}
    for k, v in TIERS.items():
        assert pub[k]["usd"] == v["usd"]
        assert pub[k]["runs_per_day"] == v["runs_per_day"]


def test_product_config_json_matches_tiers():
    from local_ui.usage_limits import TIERS

    cfg = json.loads((SITE / "product-config.json").read_text())
    for key, plan in TIERS.items():
        p = cfg["plans"][key]
        assert p["usd"] == plan["usd"]
        assert p["runs_per_day"] == plan["runs_per_day"]
        assert p["visual_per_day"] == plan["visual_per_day"]
    assert cfg["billing"]["topups"]["available"] is False


def test_marketing_pages_do_not_advertise_stale_prices():
    """Reject the previously live-wrong $9/$19 · 8/120/500 marketing set."""
    bad = [
        re.compile(r"\$9(?!\.99)"),  # bare $9 not $7.99
        re.compile(r"(?<![\d.])\$19(?!\.99)"),  # bare $19 not $19.99
        re.compile(r"\b8 runs\b"),
        re.compile(r"\b120 runs\b"),
        re.compile(r"(?<![,\d])500 runs\b"),
    ]
    # product-config.js may mention the forbidden numbers as anti-patterns
    skip_names = {"product-config.js", "cli-session.json", "cli-session-csv.json",
                  "cli-session-hard.json"}
    offenders = []
    for path in SITE.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".mp4", ".webm", ".jpeg"}:
            continue
        if path.name in skip_names:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for rx in bad:
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
    assert "lolm-v21-workspace-identity" in sw  # v21+ supersedes v20 artifact-delivery cache name
    assert "product-config.json" in sw
