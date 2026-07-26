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
