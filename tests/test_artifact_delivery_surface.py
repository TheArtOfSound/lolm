from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_design_system_does_not_load_browser_artifact_execution():
    ds = (ROOT / "site" / "lolm-ds.js").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.html").read_text(encoding="utf-8")
    assert "/artifact-delivery-ui.js" not in ds
    assert "/api/" not in app
    assert "npm install -g lolm-cli" in app


def test_artifact_delivery_module_is_an_inert_tombstone():
    js = (ROOT / "site" / "artifact-delivery-ui.js").read_text(encoding="utf-8")
    assert "available: false" in js
    assert "fetch(" not in js
    assert "createObjectURL" not in js
    assert ".innerHTML" not in js


def test_service_worker_is_documentation_only():
    sw = (ROOT / "site" / "sw.js").read_text(encoding="utf-8")
    assert "lolm-docs-v1" in sw
    assert "artifact-delivery-ui.js" not in sw
    assert 'startsWith("/api/")' in sw
