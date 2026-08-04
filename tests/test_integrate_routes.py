# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Public integrate catalog for third-party platforms."""

from local_ui.integrate_routes import INTEGRATION_CATALOG, register_integrate_routes


def test_catalog_has_core_endpoints():
    ids = {e["id"] for e in INTEGRATION_CATALOG["endpoints"]}
    assert "code_run" in ids
    assert "visual" in ids
    assert "code_receipts" in ids
    assert INTEGRATION_CATALOG["clients"]["npm"] == "lolm-nfet-client"
    assert INTEGRATION_CATALOG["clients"]["cli"] == "lolm-cli (bin: lolm)"


def test_register_on_fastapi():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    register_integrate_routes(app)
    c = TestClient(app)
    r = c.get("/api/demo/integrate")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "integrate-v1"
    assert any(e["path"].startswith("/api/demo/code/run") for e in body["endpoints"])
    o = c.get("/api/demo/integrate/openapi.json")
    assert o.status_code == 200
    assert o.json()["openapi"].startswith("3.")
