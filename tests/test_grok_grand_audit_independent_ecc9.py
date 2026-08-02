# Verification-only independent adversarial checks for
# ecc9a7a28713e1eee47821e1e8c3e51409670be1.

from __future__ import annotations

import hashlib
import inspect
import re
from pathlib import Path

from local_ui.code_agent import CodeAgent
from lolm.reliability.checkpoint_store import CheckpointStore
from lolm.reliability.closure import evaluate_closure
from lolm.reliability.run_state import RunReliabilityState
from lolm.reliability.session_ledger import SessionIntentLedger

ROOT = Path(__file__).resolve().parents[1]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Artifact closure must prove bytes, not trust booleans.
def test_acp_requires_a_hash_for_every_deliverable():
    ev = evaluate_closure(
        contract_ok=True,
        exact_manifest_ok=True,
        validators_green=True,
        open_hard=0,
        deliverable_paths=["output.pdf"],
        path_hashes={},
    )
    assert ev.ready is False


def test_pdf_closure_rejects_invalid_pdf_bytes_and_untrusted_hash():
    rs = RunReliabilityState.open("Generate output.pdf containing a short report")
    rs.note_write("output.pdf", "this is not a PDF", step=1)
    info = rs.evaluate_and_maybe_close(
        ["output.pdf"],
        path_hashes={"output.pdf": "deadbeef"},
        validators_green=True,
        step=1,
    )
    assert info["closure"]["closed"] is False


def test_pdf_special_case_cannot_bypass_exact_output_set():
    rs = RunReliabilityState.open("Create exactly one output.pdf and no helper files")
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
    assert info["closure"]["closed"] is False


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
    assert info["closure"]["closed"] is False


# Last-known-green must mean verified, reversible, exact tree state.
def test_html_cannot_be_checkpointed_green_by_arbitrary_exit_zero():
    rs = RunReliabilityState.open("Build a playable browser snake game")
    ck = rs.snapshot_if_green(
        {"index.html": "<html><canvas></canvas></html>"},
        step=1,
        compile_ok=True,
        run_ok=True,
        verifier_outputs={"run": {"ok": True, "cmd": "cat index.html"}},
    )
    assert ck is None


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
    assert regressed is True and ck is not None


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
    assert sb.files == {"index.html": "good"}


# EGCA and runtime wiring.
def test_egca_accepts_task_state_policy_object_and_extracts_action():
    rs = RunReliabilityState.open("write a small text artifact")
    decision = rs.arbitrate(
        task_state_action={"action": "branch", "reason": "dead end"},  # type: ignore[arg-type]
    )
    assert decision.action == "BRANCH_WITH_CONSTRAINTS"


def test_success_exit_code_is_not_coerced_to_failure_in_codeagent_wiring():
    src = inspect.getsource(CodeAgent.run)
    assert 'int(r.get("exit_code") or 1)' not in src


def test_html_verifier_accepts_the_documented_working_field():
    src = inspect.getsource(CodeAgent.run)
    m = re.search(r"ok_v\s*=\s*bool\((.*?)\)\n", src, re.S)
    assert m is not None
    assert "working" in m.group(1)


def test_counterfactual_branch_portfolio_is_used_by_live_loop():
    src = inspect.getsource(CodeAgent.run)
    assert (
        "self.reliability.branches.note_failure" in src
        and "self.reliability.branches.accept_branch" in src
    )


def test_retrieval_bankruptcy_is_used_by_live_loop():
    src = inspect.getsource(CodeAgent.run)
    assert (
        "self.reliability.retrieval.record" in src
        and "self.reliability.retrieval.may_retrieve" in src
    )


def test_evidence_progress_budget_receives_live_action_deltas():
    src = inspect.getsource(CodeAgent.run)
    assert "self.reliability.record_delta(" in src


# Session ledger and CLI retry/resume semantics.
def test_session_id_cannot_escape_configured_root(tmp_path):
    root = tmp_path / "sessions"
    ledger = SessionIntentLedger(session_id="../escaped", root=root)
    ledger.record_ask("hello")
    expected_root = root.resolve()
    actual = ledger._path.resolve()
    assert actual.is_relative_to(expected_root)


def test_cli_resume_transmits_checkpoint_or_uses_resume_endpoint():
    src = (ROOT / "clients/cli/bin/lolm.mjs").read_text(encoding="utf-8")
    start = src.index("async function cmdRetry")
    end = src.index("async function cmdResume")
    block = src[start:end]
    has_checkpoint_transport = bool(
        re.search(r"flags\.(checkpoint|checkpointId|resumeRunId|resumePackage)\s*=", block)
        or re.search(r"cmdCode\([^\n]*(checkpoint|resumePackage)", block)
        or re.search(r"/(resume|retry)\b", block)
        or "resumeRun(" in block
    )
    assert has_checkpoint_transport


def test_cli_has_a_local_session_writer_for_hosted_run_events():
    src = (ROOT / "clients/cli/bin/lolm.mjs").read_text(encoding="utf-8")
    assert "persistLocalSessionFromReceipt" in src
    assert "await persistLocalSessionFromReceipt(" in src


def test_cli_code_forwards_requested_network_deadlines_to_run_code():
    """The organic packaged run passed 120s idle / 300s total but died at 30s.

    cmdCode must transport the parsed deadline values into runCode rather than
    construct clientOpts and forward only credentials.
    """
    src = (ROOT / "clients/cli/bin/lolm.mjs").read_text(encoding="utf-8")
    start = src.index("async function cmdCode")
    end = src.index("async function cmdAsk")
    block = src[start:end]
    call_start = block.index("const result = await runCode({")
    call_end = block.index("\n  });", call_start)
    call = block[call_start:call_end]
    forwards_all = "...clientOpts(flags)" in call
    forwards_explicit = (
        ("timeoutMs: opts.timeoutMs" in call or "timeoutMs: flags.timeout" in call)
        and ("idleTimeoutMs: opts.idleTimeoutMs" in call or "idleTimeoutMs: flags.idleTimeout" in call)
        and ("signal: opts.signal" in call or "signal: COMMAND_ABORT.signal" in call)
    )
    assert forwards_all or forwards_explicit, (
        "lolm code ignores --timeout/--idle-timeout and cancellation wiring; "
        "the packaged organic run therefore fell back to the JS client's 30s idle default"
    )
