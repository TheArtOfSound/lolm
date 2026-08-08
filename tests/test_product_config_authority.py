"""Lock the documentation-only, open-source public product boundary."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def test_product_config_is_cli_only_and_contains_no_plans():
    cfg = json.loads((SITE / "product-config.json").read_text())
    assert cfg["product"]["mode"] == "open_source_cli"
    assert cfg["product"]["license"] == "AGPL-3.0-or-later"
    assert cfg["execution"] == {"website": False, "cli": True, "hosted_api": False}
    assert "plans" not in cfg
    assert "billing" not in cfg
    assert cfg["commercial_license"]["available"] is True
    assert cfg["commercial_license"]["public_prices"] is False


def test_public_site_has_no_active_execution_or_purchase_copy():
    forbidden = ["/api/demo/run", "/api/demo/code", "billing/checkout",
                 "runs/day", "$7.99", "$19.99"]
    offenders = []
    for path in SITE.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4", ".webm"}:
            continue
        if path.parts[-2:-1] == ("replays",):
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        for needle in forbidden:
            if needle.lower() in text:
                offenders.append(f"{path.relative_to(ROOT)}:{needle}")
    assert not offenders, "retired public product surface leaked:\n" + "\n".join(offenders[:40])


def test_retired_browser_pages_point_to_install_only():
    for name in ["app.html", "try.html", "pricing.html", "operator.html", "workspace.html"]:
        html = (SITE / name).read_text(encoding="utf-8")
        assert "npm install -g lolm-cli" in html
        assert "/install.html" in html
        assert "fetch(" not in html


def test_service_worker_caches_docs_but_never_api_or_agent_pages():
    sw = (SITE / "sw.js").read_text(encoding="utf-8")
    assert "lolm-docs-v1" in sw
    assert 'url.pathname.startsWith("/api/")' in sw
    assert "/app.html" not in sw
    assert "/try.html" not in sw


def test_public_pages_mount_the_canonical_qira_apps_launcher():
    design_script = (SITE / "lolm-ds.js").read_text(encoding="utf-8")
    design_css = (SITE / "lolm-ds.css").read_text(encoding="utf-8")
    launcher_url = "https://imagineqira.com/assets/qira-apps/qira-product-launcher.js"

    assert launcher_url in design_script
    assert 'launcher.setAttribute("current-product", "lolm")' in design_script
    assert 'launcher.setAttribute("theme", effective())' in design_script
    assert "qira-product-launcher" in design_css

    for path in SITE.rglob("*.html"):
        if path == SITE / "media" / "render_cast.html":
            continue
        html = path.read_text(encoding="utf-8")
        assert "/lolm-ds.js" in html, f"{path.relative_to(SITE)} bypasses the shared launcher layer"


def test_public_server_has_no_execution_enable_switch():
    server = (ROOT / "local_ui" / "server_public_demo.py").read_text(encoding="utf-8")
    assert "LOLM_PUBLIC_WEB_EXECUTION" not in server
    assert 'request.client, "host", "") == "testclient"' in server
    assert '"error": "PUBLIC_WEB_EXECUTION_RETIRED"' in server
