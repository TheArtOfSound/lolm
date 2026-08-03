from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_loads_artifact_delivery_observer_through_design_system():
    ds = (ROOT / "site" / "lolm-ds.js").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.html").read_text(encoding="utf-8")
    assert "/artifact-delivery-ui.js" in ds
    assert "/lolm-ds.js" in app


def test_artifact_delivery_ui_uses_dom_construction_not_innerhtml():
    js = (ROOT / "site" / "artifact-delivery-ui.js").read_text(encoding="utf-8")
    assert "artifact_manifest" in js
    assert "code_receipt" in js
    assert "artifact_manifest_sha256" in js
    assert "createObjectURL" in js
    assert ".innerHTML" not in js
    assert "textContent" in js


def test_workspace_surfaces_server_safety_refusal_without_executing_tools():
    js = (ROOT / "site" / "artifact-delivery-ui.js").read_text(encoding="utf-8")
    assert "OFFICIAL_CREDENTIAL_FABRICATION" in js
    assert "Request refused" in js
    assert "no tools ran" in js
    assert "lolm:safety-refusal" in js


def test_service_worker_precaches_new_artifact_surface_and_bumps_version():
    sw = (ROOT / "site" / "sw.js").read_text(encoding="utf-8")
    assert "lolm-v20-artifact-delivery" in sw
    assert '"/artifact-delivery-ui.js"' in sw
