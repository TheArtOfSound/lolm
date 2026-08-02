# Independent adversarial checks for commit 74c93461894c761ee2c0b838cbc30d3b780a5023.
# These tests encode the report's actual invariants rather than the implementation's
# own interface assumptions. They are verification-only and must not be merged.

from __future__ import annotations

import hashlib
import inspect
import re
from pathlib import Path

import pytest

from local_ui.code_agent import CodeAgent
from lolm.reliability.checkpoint_store import CheckpointStore
from lolm.reliability.closure import evaluate_closure
from lolm.reliability.run_state import RunReliabilityState
from lolm.reliability.session_ledger import SessionIntentLedger


ROOT = Path(__file__).resolve().parents[1]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Artifact Closure Protocol must prove bytes, not trust booleans ───────────

def test_acp_requires_a_hash_for_every_deliverable():
    ev = evaluate_closure(
        contract_ok=True,
        exact_manifest_ok=True,
        validators_green=True,
        open_hard=0,
        deliverable_paths=["output.pdf"],
        path_hashes={},
    )
    assert ev.ready is False, "ACP closed with a deliverable that had no authoritative hash"


def test_pdf_closure_rejects_invalid_pdf_bytes_and_untrusted_hash():
    rs = RunReliabilityState.open("Generate output.pdf containing a short report")
    rs.note_write("output.pdf", "this is not a PDF", step=1)
    info = rs.evaluate_and_maybe_close(
        ["output.pdf"],
        path_hashes={"output.pdf": "deadbeef"},
        validators_green=True,
        step=1,
    )
    assert info["closure"]["closed"] is False, (
        "PDF closure accepted arbitrary text and a caller-supplied fake hash"
    )


def test_pdf_special_case_cannot_bypass_exact_output_set():
    rs = RunReliabilityState.open(
        "Create exactly one output.pdf and no helper files",
    )
    rs.note_write("output.pdf", "%PDF-1.7\n", step=1)
    rs.note_write("helper.py", "print('helper')\n", step=1)
    info = rs.evaluate_and_maybe_close(
        ["output.pdf", "helper.py"],
        path_hashes={
            "output.pdf": _sha("%PDF-1.7\n"),
            "helper.py": _sha("print('helper')\n"),
        },
        validators_green=True,
        step=1,
    )
    assert info["closure"]["closed"] is False, (
        "PDF special-case closure overrode an exact-count manifest violation"
    )


def test_pdf_special_case_cannot_override_contradictory_contract():
    rs = RunReliabilityState.open("Generate output.pdf")
    rs.contract.contradictory = True
    rs.contract.contradictions = ["forced contradiction for invariant test"]
    rs.note_write("output.pdf", "%PDF-1.7\n", step=1)
    info = rs.evaluate_and_maybe_close(
        ["output.pdf"],
        path_hashes={"output.pdf": _sha("%PDF-1.7\n")},
        validators_green=True,
        step=1,
    )
    assert info["closure"]["closed"] is False, (
        "PDF special-case closure erased contract contradiction evidence"
    )


# ── Last-known-green must mean verified, reversible, exact tree state ────────

def test_html_cannot_be_checkpointed_green_by_arbitrary_exit_zero():
    rs = RunReliabilityState.open("Build a playable browser snake game")
    ck = rs.snapshot_if_green(
        {"index.html": "<html><canvas></canvas></html>"},
        step=1,
        compile_ok=True,
        run_ok=True,
        verifier_outputs={"run": {"ok": True, "cmd": "cat index.html"}},
    )
    assert ck is None, (
        "HTML was declared last-known-green without html.render or an equivalent validator"
    )


def test_behavioral_regression_triggers_rollback_even_when_syntax_stays_valid():
    store = CheckpointStore()
    good = {"index.html": "<html><script>requestAnimationFrame(loop)</script></html>"}
    store.force_green(
        file_contents=good,
        contract_coverage=1.0,
        green_hard=2,
        open_hard=0,
        verifier_outputs={"html.render": {"ok": True}},
        step=1,
    )
    changed = {"index.html": _sha("<html><script>// blank</script></html>")}
    regressed, ck = store.has_regressed(changed, compile_ok=True)
    assert regressed is True and ck is not None, (
        "LGTS only detects compile failures and misses behavior/contract regressions"
    )


def test_lgts_restore_removes_files_absent_from_checkpoint():
    store = CheckpointStore()
    store.force_green(
        file_contents={"index.html": "good"},
        contract_coverage=1.0,
        green_hard=1,
        open_hard=0,
        step=1,
    )

    class Sandbox:
        def __init__(self):
            self.files = {"index.html": "bad", "helper.py": "unapproved"}

        def write_file(self, path, content, reason=""):
            self.files[path] = content
            return {"diff": ""}

        def list_files(self):
            return list(self.files)

        def delete_file(self, path):
            self.files.pop(path, None)

    sb = Sandbox()
    store.materialize_to_sandbox(sb)
    assert sb.files == {"index.html": "good"}, (
        "Rollback restored known files but left post-checkpoint extras in the tree"
    )


# ── EGCA and runtime wiring ──────────────────────────────────────────────────

def test_egca_accepts_task_state_policy_object_and_extracts_action():
    rs = RunReliabilityState.open("write a small text artifact")
    # The live CodeAgent passes policy_action(self.task_state), which is a dict.
    decision = rs.arbitrate(
        task_state_action={"action": "branch", "reason": "dead end"},  # type: ignore[arg-type]
    )
    assert decision.action == "BRANCH_WITH_CONSTRAINTS"


def test_success_exit_code_is_not_coerced_to_failure_in_codeagent_wiring():
    src = inspect.getsource(CodeAgent.run)
    assert 'int(r.get("exit_code") or 1)' not in src, (
        "exit_code=0 is falsy, so `or 1` reports every successful run as a failure to SFL/VCG"
    )


def test_html_verifier_accepts_the_documented_working_field():
    src = inspect.getsource(CodeAgent.run)
    m = re.search(r"ok_v\s*=\s*bool\((.*?)\)\n", src, re.S)
    assert m is not None, "could not locate html verifier acceptance expression"
    assert "working" in m.group(1), (
        "code_routes._verify_html returns `working`; CodeAgent only checks `ok`/`passed`"
    )


def test_counterfactual_branch_portfolio_is_used_by_live_loop():
    src = inspect.getsource(CodeAgent.run)
    assert (
        "self.reliability.branches.note_failure" in src
        and "self.reliability.branches.accept_branch" in src
    ), "Counterfactual Branch Portfolio exists but is not wired into live branch execution"


def test_retrieval_bankruptcy_is_used_by_live_loop():
    src = inspect.getsource(CodeAgent.run)
    assert (
        "self.reliability.retrieval.record" in src
        and "self.reliability.retrieval.may_retrieve" in src
    ), "Retrieval Bankruptcy exists as a module but does not gate live retrievals"


def test_evidence_progress_budget_receives_live_action_deltas():
    src = inspect.getsource(CodeAgent.run)
    assert "self.reliability.record_delta(" in src, (
        "EvidenceProgressBudget is checked, but the live loop never records evidence deltas"
    )


# ── Session ledger and CLI retry/resume semantics ────────────────────────────

def test_session_id_cannot_escape_configured_root(tmp_path):
    root = tmp_path / "sessions"
    ledger = SessionIntentLedger(session_id="../escaped", root=root)
    ledger.record_ask("hello")
    expected_root = root.resolve()
    actual = ledger._path.resolve()  # verification-only access to concrete storage path
    assert actual.is_relative_to(expected_root), (
        f"session id escaped ledger root: {actual} not under {expected_root}"
    )


def test_cli_resume_transmits_checkpoint_or_uses_resume_endpoint():
    src = (ROOT / "clients/cli/bin/lolm.mjs").read_text(encoding="utf-8")
    start = src.index("async function cmdRetry")
    end = src.index("async function cmdResume")
    block = src[start:end]
    has_checkpoint_transport = bool(
        re.search(r"flags\.(checkpoint|checkpointId|resumeRunId)\s*=", block)
        or re.search(r"cmdCode\([^\n]*checkpoint", block)
        or re.search(r"/(resume|retry)\b", block)
        or "resumeRun(" in block
    )
    assert has_checkpoint_transport, (
        "`resume` only starts cmdCode(task) again; checkpoint_id is displayed but never transported"
    )


def test_cli_has_a_local_session_writer_for_hosted_run_events():
    src = (ROOT / "clients/cli/bin/lolm.mjs").read_text(encoding="utf-8")
    start = src.index("function sessionDir")
    end = src.index("async function cmdInspect")
    block = src[start:end]
    has_writer = bool(
        re.search(r"writeFile\([^\n]*(sessionDir|sessions)", block)
        or "persistSession" in block
        or "saveSession" in block
    )
    assert has_writer, (
        "Server-side SessionIntentLedger files are not copied to the user's local CLI ledger, "
        "so `lolm last/retry/resume` cannot see hosted runs"
    )
