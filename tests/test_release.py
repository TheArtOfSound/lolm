# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the self-driving release pipeline (gates, versioning, receipt, learning)."""

import json

from lolm.release import gates as G
from lolm.release import versioning as V
from lolm.release.receipt import compute_verdict, DailyReceipt, receipt_to_markdown, VERDICTS
from lolm.release import learning as L


# ── safety scanners ──────────────────────────────────────────────────────────
def test_secret_scan_catches_real_secrets():
    diff = '+aws_secret_access_key = "wJalrXUtnFEMIz7MDENGbPxRfiCYzAbCdEfGhIjK1n2"\n+const x = 1'  # pragma: allowlist secret
    assert G.secret_scan(diff).passed is False
    diff2 = '+sk-abcdefghijklmnopqrstuvwxyz0123456789\n'  # pragma: allowlist secret
    assert G.secret_scan(diff2).passed is False
    assert G.secret_scan('+token = "ghp_' + "a" * 36 + '"').passed is False


def test_secret_scan_honors_allowlist_pragma():
    # an intentional fixture marked with the pragma must not block a ship
    flagged = '+key = "ghp_' + "b" * 36 + '"  # pragma: allowlist secret'
    assert G.secret_scan(flagged).passed is True


def test_secret_scan_allows_placeholders_and_clean_code():
    assert G.secret_scan('+api_key = os.environ["API_KEY"]\n+x = 2').passed is True
    assert G.secret_scan('+const token = process.env.NPM_TOKEN').passed is True
    assert G.secret_scan('+# set your_api_key in the env').passed is True
    assert G.secret_scan('-AKIA1234567890ABCDEF  # removed line is ignored').passed is True  # pragma: allowlist secret


def test_protected_files_gate():
    assert G.protected_files_touched(["lolm/foo.py", "site/index.html"]).passed is True
    assert G.protected_files_touched([".env"]).passed is False
    assert G.protected_files_touched(["deploy/prod_secret_key.txt"]).passed is False
    assert G.protected_files_touched(["clients/js/.npmrc"]).passed is False
    assert G.protected_files_touched(["keys/id_ed25519"]).passed is False


# ── gates ────────────────────────────────────────────────────────────────────
def _full_merge_gate(all_pass=True):
    g = G.MergeGate()
    for name in G.MergeGate.REQUIRED:
        g.add(G.GateResult(name, all_pass or name != "tests", "ok" if all_pass else "ran"))
    return g


def test_merge_gate_requires_all_checks():
    g = G.MergeGate()
    g.add(G.GateResult("tests", True))
    assert g.passed is False            # missing required checks
    assert "evals" in g.missing()
    assert _full_merge_gate(True).passed is True


def test_merge_gate_blocks_on_failed_test():
    g = _full_merge_gate(all_pass=False)   # tests=False
    assert g.passed is False
    assert any("tests" in b for b in g.blockers)


def test_evaluate_gates_aggregates_blockers():
    good = _full_merge_gate(True)
    bad = G.PublishGate()
    bad.add(G.GateResult("build", False, "tsc error"))
    out = G.evaluate_gates(good, bad)
    assert out["passed"] is False
    assert any("PublishGate" in b for b in out["blockers"])


# ── versioning ───────────────────────────────────────────────────────────────
def test_versioning():
    assert V.bump_patch("0.1.1") == "0.1.2"
    assert V.bump_minor("0.1.1") == "0.2.0"
    assert V.bump_major("0.1.1") == "1.0.0"
    assert V.canary_version("0.1.1", "2026-06-15", 3) == "0.1.1-canary.20260615.3"


def test_pkg_version_roundtrip(tmp_path):
    p = tmp_path / "package.json"
    p.write_text(json.dumps({"name": "x", "version": "1.2.3"}))
    assert V.read_pkg_version(p) == "1.2.3"
    V.write_pkg_version(p, "1.2.4")
    assert V.read_pkg_version(p) == "1.2.4"


# ── verdicts ─────────────────────────────────────────────────────────────────
def test_verdict_no_change():
    assert compute_verdict(changed=False, gates={}, merged=False, canary=None,
                           stable=None, deployed=None, blockers=[]) == "no_change_needed"


def test_verdict_blocked_by_tests():
    v = compute_verdict(changed=True, gates={"passed": False}, merged=False, canary=None,
                        stable=None, deployed=None, blockers=["MergeGate: tests: 1 failed"])
    assert v == "blocked_by_tests"


def test_verdict_blocked_by_security():
    v = compute_verdict(changed=True, gates={"passed": False}, merged=False, canary=None,
                        stable=None, deployed=None,
                        blockers=["MergeGate: no_secret_introduced: leaked key"])
    assert v == "blocked_by_security"


def test_verdict_ship_progression():
    assert compute_verdict(changed=True, gates={"passed": True}, merged=True, canary=None,
                           stable=None, deployed=None, blockers=[]) == "shipped_to_main"
    assert compute_verdict(changed=True, gates={"passed": True}, merged=True,
                           canary={"ok": True}, stable=None, deployed=None,
                           blockers=[]) == "shipped_to_npm_canary"
    assert compute_verdict(changed=True, gates={"passed": True}, merged=True,
                           canary={"ok": True}, stable={"ok": True}, deployed=None,
                           blockers=[]) == "shipped_to_npm_stable"
    assert compute_verdict(changed=True, gates={"passed": True}, merged=True,
                           canary={"ok": True}, stable={"ok": True},
                           deployed={"ok": True}, blockers=[]) == "deployed_live"


def test_verdict_is_always_in_taxonomy():
    v = compute_verdict(changed=True, gates={"passed": True}, merged=False, canary=None,
                        stable=None, deployed=None, blockers=["DeployGate: health: 503"])
    assert v in VERDICTS


def test_receipt_markdown_renders():
    r = DailyReceipt(run_id="daily_x", date="2026-06-15", verdict="shipped_to_main",
                     files_changed=["CHANGELOG.md"], rollback_command="git revert abc")
    r.gates = {"merge": {"passed": True, "checks": [
        {"name": "tests", "passed": True, "detail": "257 passed"}]}}
    md = receipt_to_markdown(r.to_dict())
    assert "shipped_to_main" in md and "257 passed" in md and "git revert abc" in md


# ── learning (no fake learning) ──────────────────────────────────────────────
def test_gather_learning_empty(tmp_path):
    out = L.gather_learning(tmp_path)
    assert out["memories_written"] == 0
    assert out["sources_present"] == []


def test_find_targets_only_when_concrete(tmp_path):
    # no learning → only the always-safe dependency audit, nothing invented
    t0 = L.find_targets(tmp_path, L.gather_learning(tmp_path))
    assert all(t["kind"] in ("dependency_audit",) for t in t0)

    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "hf_memory.jsonl").write_text(json.dumps({"memory_id": "m1"}) + "\n")
    (runs / "hf_candidates.jsonl").write_text(json.dumps({"repo_id": "a/b", "trained": False}) + "\n")
    learning = L.gather_learning(tmp_path)
    kinds = {t["kind"] for t in L.find_targets(tmp_path, learning)}
    assert "changelog_entry" in kinds
    assert "controller_training_candidates" in kinds
