# Copyright (c) 2026 Qira LLC
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local access and commercial-entitlement compatibility proofs."""
import hashlib
import types

import pytest

from local_ui import usage_limits as ul

PW = "correct-horse"
PW_HASH = hashlib.sha256(PW.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    ul.init(tmp_path)
    monkeypatch.delenv("LOLM_ADMIN_PASS_SHA256", raising=False)
    monkeypatch.delenv("LOLM_SIGNING_SECRET", raising=False)


def _req(headers=None, host="203.0.113.9"):
    return types.SimpleNamespace(headers=headers or {},
                                 client=types.SimpleNamespace(host=host))


def test_hosted_quotas_are_retired():
    assert ul.enforced() is False
    result = ul.check_request(_req())
    assert result["allowed"] and result["unlimited"]
    assert result["hosted_execution"] is False


def test_usage_status_has_no_price_or_quota():
    status = ul.usage_status(_req())
    assert status["unlimited"] and status["runs"]["limit"] is None
    assert status["upgrade_hint"] is False
    assert all("usd" not in row for row in status["tiers"].values())


def test_admin_unlock_is_signed(monkeypatch):
    monkeypatch.setenv("LOLM_ADMIN_PASS_SHA256", PW_HASH)
    assert ul.admin_unlock("wrong") is None
    token = ul.admin_unlock(PW)
    assert token and ul.is_admin(token)
    assert not ul.is_admin(token[:-2] + "zz")


def test_commercial_entitlement_round_trip():
    token = ul.mint_license("agreement-123", "plus")
    assert ul.read_license(token) == {"sub_id": "agreement-123", "tier": "plus"}
    assert ul.read_license(token[:-2] + "zz") is None
