# Copyright (c) 2026 Qira LLC
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Documentation-only integration catalog."""

from local_ui.integrate_routes import INTEGRATION_CATALOG, register_integrate_routes


def test_catalog_points_to_the_local_cli_only():
    assert INTEGRATION_CATALOG["version"] == "cli-only-v2"
    assert INTEGRATION_CATALOG["hosted_execution"] is False
    assert INTEGRATION_CATALOG["endpoints"] == []
    assert INTEGRATION_CATALOG["clients"] == {"cli": "lolm-cli (bin: lolm)"}
    assert INTEGRATION_CATALOG["install"] == "npm install -g lolm-cli"
    assert "billing" not in INTEGRATION_CATALOG


def test_catalog_and_openapi_publish_no_execution_paths():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    register_integrate_routes(app)
    client = TestClient(app)
    body = client.get("/api/demo/integrate").json()
    assert body["version"] == "cli-only-v2"
    assert body["hosted_execution"] is False
    assert body["endpoints"] == []
    openapi = client.get("/api/demo/integrate/openapi.json").json()
    assert openapi["openapi"].startswith("3.")
    assert openapi["paths"] == {}
