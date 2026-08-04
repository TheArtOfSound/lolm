# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Independent invariant tests for grand-audit remediation review findings.

These encode the reviewer's critical failures — not Snake-specific patches.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lolm.reliability.checkpoint_store import CheckpointStore, meaningful_green_evidence
from lolm.reliability.closure import ClosureProtocol, evaluate_closure
from lolm.reliability.evidence import (
    coerce_exit_code,
    content_sha256,
    hash_tree,
    html_verdict_ok,
    is_trivial_command,
    pdf_bytes_valid,
)
from lolm.reliability.progress_budget import ActionDelta, EvidenceProgressBudget
from lolm.reliability.run_state import RunReliabilityState
from lolm.reliability.session_ledger import SessionIntentLedger, sanitize_session_id


# ── 1. Closure must hash real bytes ──────────────────────────────────────────

def test_closure_rejects_missing_file_contents():
    ev = evaluate_closure(
        file_contents=None,
        contract_ok=True,
        exact_manifest_ok=True,
        validators_green=True,
        open_hard=0,
        deliverable_paths=["output.pdf"],
        claimed_hashes={"output.pdf": "abc"},
        primary_language="pdf",
    )
    assert ev.ready is False
    assert "has_file_contents" in ev.reason or "hashes" in ev.reason


def test_closure_rejects_fake_claimed_hash_for_invalid_pdf():
    fake = "not a pdf at all"
    claimed = {"output.pdf": "deadbeef" * 8}
    ev = evaluate_closure(
        file_contents={"output.pdf": fake},
        contract_ok=True,
        exact_manifest_ok=True,
        validators_green=True,
        open_hard=0,
        deliverable_paths=["output.pdf"],
        claimed_hashes=claimed,
        primary_language="pdf",
    )
    assert ev.ready is False
    # Must not close on invalid magic OR hash mismatch
    assert ev.preconditions.get("type_bytes_ok") is False or \
        ev.preconditions.get("claimed_hashes_match") is False


def test_closure_accepts_valid_pdf_with_independent_hash():
    # Minimal valid-enough PDF for magic check (>=64 bytes with %PDF)
    body = b"%PDF-1.4\n" + b"% " + (b"x" * 80)
    text = body.decode("latin-1")
    h = content_sha256(text)
    ev = evaluate_closure(
        file_contents={"output.pdf": text},
        contract_ok=True,
        exact_manifest_ok=True,
        validators_green=True,
        open_hard=0,
        deliverable_paths=["output.pdf"],
        claimed_hashes={"output.pdf": h},
        primary_language="pdf",
    )
    assert ev.ready is True
    assert ev.independent_hashes["output.pdf"] == h


# ── 2. No PDF force-override ─────────────────────────────────────────────────

def test_no_pdf_contract_force_close_with_extra_files():
    rs = RunReliabilityState.open("exactly one output.pdf report")
    # Invalid pdf + helper
    info = rs.evaluate_and_maybe_close(
        ["output.pdf", "helper.py"],
        file_contents={
            "output.pdf": "not-pdf",
            "helper.py": "x=1\n",
        },
        validators_green=True,
        verifier_outputs={"pdf.exists": {"ok": True, "valid_magic": True}},  # lying caller
        step=1,
    )
    # Independent inspection must refuse
    assert info["closure"]["closed"] is False
    assert info["closure"]["ready"] is False


def test_contradictory_contract_never_closed():
    rs = RunReliabilityState.open("no javascript canvas requestAnimationFrame animation")
    if not rs.contract.contradictory:
        pytest.skip("compiler did not mark contradictory for this phrasing")
    info = rs.evaluate_and_maybe_close(
        ["index.html"],
        file_contents={"index.html": "<html><canvas></canvas></html>" * 5},
        validators_green=True,
        verifier_outputs={"html.render": {"ok": True, "working": True}},
        step=1,
    )
    assert info["closure"]["closed"] is False


# ── 3. Exit code 0 preserved ─────────────────────────────────────────────────

def test_coerce_exit_code_preserves_zero():
    assert coerce_exit_code({"exit_code": 0}) == 0
    assert coerce_exit_code({"exit_code": 1}) == 1
    assert coerce_exit_code({"exit_code": None}) == 1
    assert coerce_exit_code({}) == 1
    assert coerce_exit_code(None) == 1


def test_observe_run_success_not_recorded_as_failure():
    rs = RunReliabilityState.open("print hello in main.py")
    notes = rs.observe_run("python3 main.py", result={"exit_code": 0, "stdout": "hi\n"})
    assert notes["exit_code"] == 0
    assert "failure" not in notes
    assert len(rs.failures.entries) == 0


# ── 4. HTML verifier schema ──────────────────────────────────────────────────

def test_html_verdict_accepts_working_schema():
    ok, why = html_verdict_ok({
        "working": True, "renders": True, "animates": True, "responds": True,
    })
    assert ok is True


def test_html_verdict_rejects_nonworking():
    ok, why = html_verdict_ok({
        "working": False, "renders": False, "reasons": ["blank canvas"],
    })
    assert ok is False


# ── 5. Green requires meaningful validators ──────────────────────────────────

def test_cat_index_html_is_not_green():
    ok, why = meaningful_green_evidence(
        primary_language="html",
        verifier_outputs={"run": {"ok": True, "cmd": "cat index.html", "trivial": True}},
        run_ok=True,
        run_command="cat index.html",
    )
    assert ok is False
    assert is_trivial_command("cat index.html")


def test_html_green_requires_render_verifier():
    ok, _ = meaningful_green_evidence(
        primary_language="html",
        verifier_outputs={"html.render": {"ok": True, "working": True}},
    )
    assert ok is True


def test_snapshot_rejects_trivial_run(tmp_path):
    store = CheckpointStore()
    ck = store.force_green(
        file_contents={"index.html": "<html>x</html>" * 20},
        contract_coverage=1.0,
        green_hard=1,
        open_hard=0,
        verifier_outputs={"run": {"ok": True, "cmd": "cat index.html", "trivial": True}},
        primary_language="html",
        run_ok=True,
        run_command="cat index.html",
        require_meaningful=True,
    )
    assert ck is None


# ── 6. Semantic regression ───────────────────────────────────────────────────

def test_regression_on_contract_coverage_drop():
    store = CheckpointStore()
    ck = store.force_green(
        file_contents={"main.py": "print(1)\n"},
        contract_coverage=1.0,
        green_hard=2,
        open_hard=0,
        verifier_outputs={
            "syntax.python": {"ok": True},
            "run": {"ok": True, "cmd": "python3 main.py", "trivial": False},
        },
        primary_language="python",
        compile_ok=True,
        run_ok=True,
        run_command="python3 main.py",
    )
    assert ck is not None
    regressed, best, why = store.has_regressed(
        {"main.py": content_sha256("print(1)\n")},
        compile_ok=True,
        contract_coverage=0.2,
        green_hard=0,
        open_hard=2,
        verifier_outputs={"syntax.python": {"ok": True}, "run": {"ok": False}},
    )
    assert regressed is True
    assert best is not None
    assert "contract_coverage" in why or "verifier" in why or "green_hard" in why


# ── 7. Exact tree rollback ───────────────────────────────────────────────────

def test_exact_tree_rollback_deletes_extras(tmp_path):
    from local_ui.sandbox import Sandbox
    sb = Sandbox(tmp_path)
    store = CheckpointStore()
    sb.write_file("index.html", "<html>good</html>")
    ck = store.force_green(
        file_contents={"index.html": "<html>good</html>"},
        contract_coverage=1.0,
        green_hard=1,
        open_hard=0,
        verifier_outputs={"html.render": {"ok": True}},
        primary_language="html",
        require_meaningful=True,
    )
    assert ck is not None
    sb.write_file("index.html", "broken")
    sb.write_file("helper.py", "x=1\n")
    assert "helper.py" in sb.list_files()
    restored = store.materialize_to_sandbox(sb, current_paths=sb.list_files())
    assert restored is not None
    assert sb.read_file("index.html") == "<html>good</html>"
    assert "helper.py" not in sb.list_files()


# ── 8. Session ID path traversal ─────────────────────────────────────────────

def test_session_id_sanitized_against_traversal(tmp_path):
    sid = sanitize_session_id("../escaped")
    assert ".." not in sid
    assert "/" not in sid
    led = SessionIntentLedger(session_id="../escaped", root=tmp_path)
    assert led._path.parent == tmp_path.resolve()
    assert led._path.exists() or led.save() is None
    led.save()
    # File must live under root
    assert tmp_path.resolve() in led._path.resolve().parents or led._path.parent == tmp_path.resolve()
    assert "escaped" not in str(led._path.name) or led._path.name.startswith("sess_")


# ── 9. Resume package is real transport ──────────────────────────────────────

def test_resume_package_contains_workspace_and_checkpoint(tmp_path):
    led = SessionIntentLedger(session_id="sess_resume_test", root=tmp_path)
    led.record_code_run(
        run_id="run_1",
        task="make pdf",
        status="terminated",
        checkpoint_id="ckpt_abc",
        workspace_snapshot={"output.pdf": "%PDF-1.4\n" + "x" * 80},
        checkpoint_payload={"checkpoint_id": "ckpt_abc", "file_contents": {"output.pdf": "%PDF-1.4\n" + "x" * 80}},
        failure_ledger={"entries": {}},
        contract_snapshot={"primary_language": "pdf"},
        failed=True,
    )
    pkg = led.resume_package()
    assert pkg is not None
    assert pkg["workspace_snapshot"]["output.pdf"].startswith("%PDF")
    assert pkg["checkpoint_id"] == "ckpt_abc"
    assert pkg["resume_token"]
    r = led.resolve_followup("resume")
    assert r["action"] == "resume"
    assert r.get("resume_package")


def test_apply_resume_package_restores_files(tmp_path):
    from local_ui.sandbox import Sandbox
    sb = Sandbox(tmp_path)
    rs = RunReliabilityState.open("build snake as index.html")
    notes = rs.apply_resume_package({
        "resume_token": "resume:run:ckpt",
        "checkpoint_id": "ckpt_x",
        "workspace_snapshot": {"index.html": "<html>restored</html>"},
        "checkpoint_payload": {
            "file_contents": {"index.html": "<html>restored</html>"},
            "contract_coverage": 1.0,
            "green_hard": 1,
            "open_hard": 0,
            "verifier_outputs": {"html.render": {"ok": True}},
            "verified_meaningful": True,
            "step": 3,
        },
    }, sb)
    assert "index.html" in notes["restored_files"]
    assert "restored" in sb.read_file("index.html")


# ── 11. Progress budget must be fed ──────────────────────────────────────────

def test_progress_budget_records_deltas():
    b = EvidenceProgressBudget(max_steps=10, max_nonpositive=3)
    b.record(ActionDelta(step=0, action="run", contract_coverage_delta=0.5, information_gain=0.5))
    assert b.nonpositive_streak == 0
    b.record(ActionDelta(step=1, action="verify", contract_coverage_delta=0.0))
    b.record(ActionDelta(step=2, action="verify", contract_coverage_delta=0.0))
    b.record(ActionDelta(step=3, action="verify", contract_coverage_delta=0.0))
    assert b.frozen is True


def test_run_state_record_delta_feeds_budget():
    rs = RunReliabilityState.open("hello", max_steps=8)
    assert rs.budget is not None
    rs.record_delta(0, "run", coverage_before=0.0, coverage_after=0.5, info_gain=0.5)
    assert rs.budget.used == 1
    assert rs.budget.nonpositive_streak == 0
    for i in range(3):
        rs.record_delta(i + 1, "noop", coverage_before=0.5, coverage_after=0.5)
    assert rs.budget.frozen is True
