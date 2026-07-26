# Copyright (c) 2026 Qira LLC. All rights reserved.
from local_ui import code_receipts as cr


def test_ledger_chains_and_tails(tmp_path, monkeypatch):
    path = cr.init(tmp_path)
    assert path.name == "code_receipts.jsonl"
    r1 = cr.append({"receipt_sha": "aaa", "task": "print 1", "ok": True, "verdict": "shipped"})
    r2 = cr.append({"receipt_sha": "bbb", "task": "print 2", "ok": False, "verdict": "stuck"})
    assert r1["ledger_sha"] and r2["prev_ledger_sha"] == r1["ledger_sha"]
    rows = cr.tail(10)
    assert len(rows) == 2
    assert rows[0]["receipt_sha"] == "aaa"
    st = cr.stats()
    assert st["recent"] == 2 and st["ok"] == 1 and st["fail"] == 1


def test_demo_seed_only_when_empty(tmp_path):
    cr.init(tmp_path)
    assert cr.ensure_demo_seed() is True
    assert cr.ensure_demo_seed() is False  # no double-seed
    rows = cr.tail(10)
    assert len(rows) == 2
    assert all(r.get("demo") for r in rows)


def test_ensure_selftest_receipt_runs_real_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_CODE_RECEIPT_DIR", str(tmp_path))
    cr.init(tmp_path)
    # empty ledger
    assert cr.tail(5) == []
    row = cr.ensure_selftest_receipt()
    assert row is not None
    assert row.get("selftest") is True
    assert row.get("demo") is False
    assert row.get("source") == "selftest"
    assert row.get("ok") is True
    assert "42" in (row.get("last_stdout_tail") or "")
    # idempotent
    assert cr.ensure_selftest_receipt() is None
    rows = cr.tail(10)
    assert sum(1 for r in rows if r.get("selftest")) == 1


def test_demo_seed_then_selftest(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_CODE_RECEIPT_DIR", str(tmp_path / "led"))
    cr.init(tmp_path / "led")
    assert cr.ensure_demo_seed() is True
    assert cr.ensure_demo_seed() is False  # already seeded
    # selftest still lands alongside demos
    row = cr.ensure_selftest_receipt()
    assert row and row.get("selftest")
    kinds = [r.get("source") for r in cr.tail(20)]
    assert "demo_seed" in kinds and "selftest" in kinds
