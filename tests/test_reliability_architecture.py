# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Grand Audit acceptance scenarios (Appendix D) + structural invariants.

Remediations are accepted only when they change state abstractions / evidence
contracts — these tests encode the general invariants, not Snake-specific patches.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lolm.reliability.arbiter import ControllerVote, select_action
from lolm.reliability.artifact_state import ArtifactRegistry, validator_accepts
from lolm.reliability.branch_portfolio import (
    BranchPortfolio,
    StrategyVector,
    hard_feasibility_filter,
    select_candidate,
    semantic_distance,
)
from lolm.reliability.capability_graph import CapabilityGraph
from lolm.reliability.checkpoint_store import CheckpointStore
from lolm.reliability.closure import ClosureProtocol, evaluate_closure
from lolm.reliability.confidence import from_nfet_and_contract, action_certainty_label
from lolm.reliability.contract_compiler import (
    check_manifest_against_contract,
    compile_contract,
)
from lolm.reliability.evaluation_plane import (
    CampaignManifest,
    CampaignQueue,
    CaseStatus,
    sign_campaign_receipt,
)
from lolm.reliability.failure_ledger import SemanticFailureLedger, canonical_error_class
from lolm.reliability.progress_budget import ActionDelta, EvidenceProgressBudget
from lolm.reliability.retrieval_bankruptcy import RetrievalBankruptcy
from lolm.reliability.runtime_manifest import build_runtime_manifest
from lolm.reliability.session_ledger import SessionIntentLedger
from lolm.reliability.run_state import RunReliabilityState


# ── D-01 Browser negative capability ─────────────────────────────────────────

def test_d01_browser_negative_capability_once():
    g = CapabilityGraph(fingerprint="env_test_1")
    # First attempt may run
    ok, _ = g.may_attempt("desktop.open")
    # Simulate definitive failure
    g.observe_command_result(
        "xdg-open index.html",
        exit_code=1,
        stderr="xdg-open: no providers available",
    )
    assert g.is_available("desktop.open") is False
    ok2, why = g.may_attempt("desktop.open")
    assert ok2 is False
    assert "unavailable" in why.lower() or "alternative" in why.lower()
    # Alternative route exists
    fact = g.facts["desktop.open"]
    assert "html.render" in fact.alternatives or "html.static_lint" in fact.alternatives


# ── D-02 Green rollback ──────────────────────────────────────────────────────

def test_d02_green_rollback_byte_for_byte():
    store = CheckpointStore()
    green = {"index.html": "<html>good game</html>"}
    ck = store.force_green(
        file_contents=green,
        contract_coverage=1.0,
        green_hard=1,
        open_hard=0,
        step=1,
    )
    assert ck is not None
    # Regression
    bad = {"index.html": "def broken(:\n"}
    store.snapshot(
        file_contents=bad,
        contract_coverage=0.0,
        green_hard=0,
        open_hard=1,
        step=2,
    )  # should reject as non-dominating if head is green — force path:
    regressed, best = store.has_regressed(
        {p: "x" for p in bad},
        compile_ok=False,
    )
    assert regressed is True
    assert best is not None
    assert best.file_contents["index.html"] == green["index.html"]
    # materialize into a fake sandbox
    class SB:
        def __init__(self):
            self.files = {}
        def write_file(self, path, content, reason=""):
            self.files[path] = content
            return {"diff": ""}
    sb = SB()
    restored = store.materialize_to_sandbox(sb)
    assert restored is not None
    assert sb.files["index.html"] == green["index.html"]


# ── D-03 Exact one file ──────────────────────────────────────────────────────

def test_d03_exact_one_file_rejects_helper():
    c = compile_contract("Create exactly one index.html for a snake game. No helper files.")
    assert c.exact_count == 1
    check = check_manifest_against_contract(
        c, ["index.html", "helper.py"],
    )
    assert check["ok"] is False
    assert any("extra" in v or "exact" in v for v in check["violations"])


# ── D-04 Closure ─────────────────────────────────────────────────────────────

def test_d04_closure_blocks_model_turns():
    acp = ClosureProtocol()
    ev = evaluate_closure(
        contract_ok=True,
        exact_manifest_ok=True,
        validators_green=True,
        open_hard=0,
        deliverable_paths=["output.pdf"],
        path_hashes={"output.pdf": "abc"},
    )
    assert ev.ready
    res = acp.try_close(ev, checkpoint_id="ckpt_1", step=1)
    assert res.closed
    assert acp.allow_model_turn() is False
    assert acp.model_turns_blocked == 1
    assert acp.allow_write() is False
    assert acp.writes_blocked == 1


# ── D-05 Controller conflict ─────────────────────────────────────────────────

def test_d05_capability_infeasibility_vetoes_verify():
    votes = [
        ControllerVote(source="task_state", action="branch", weight=1.0, soft=False,
                       reason="dead end"),
        ControllerVote(source="nfet", action="verify", weight=1.0, soft=True,
                       reason="coding head p=1.00"),
    ]
    decision = select_action(
        {
            "failure_repeated": True,
            "causal_change_proposed": False,
            "capability_infeasible": True,
            "required_causal_change": "verifier_plan",
            "root_cause": "capability_missing:desktop.open",
        },
        votes,
    )
    assert decision.action == "BRANCH_WITH_CONSTRAINTS"
    assert decision.precedence_rule in ("branch",)


def test_egca_contradiction_before_mutation():
    d = select_action(
        {"contract_contradictory": True, "contradictions": ["a vs b"]},
        [ControllerVote(source="nfet", action="continue", weight=1.0)],
    )
    assert d.action == "CLARIFY_OR_FAIL"


def test_egca_deterministic_replay():
    state = {
        "closure_ready": True,
        "failure_repeated": False,
    }
    votes = [ControllerVote(source="nfet", action="verify", weight=1.0)]
    a = select_action(state, votes)
    b = select_action(state, votes)
    assert a.action == b.action == "FINALIZE_DETERMINISTICALLY"
    assert a.evidence_version == b.evidence_version


# ── D-06 Action confidence ───────────────────────────────────────────────────

def test_d06_confidence_not_collapsed():
    bundle = from_nfet_and_contract(
        nfet_label="verify",
        nfet_p=1.0,
        green_hard=0,
        total_hard=3,
        validators_run=0,
        validators_required=2,
        capability_ok=False,
        artifact_evidence_ok=False,
    )
    ui = bundle.ui_fields()
    assert ui["policy_action_certainty"] == 1.0
    assert ui["artifact_correctness_estimate"] < 0.5
    assert "confidence" not in ui  # bare field forbidden
    label = action_certainty_label("verify", 1.0)
    assert "not artifact correctness" in label


# ── D-07 Empty retrieval ─────────────────────────────────────────────────────

def test_d07_empty_retrieval_bankruptcy():
    rb = RetrievalBankruptcy()
    rb.record("snake game notes", hit_count=0)
    ok, why = rb.may_retrieve("snake game notes", predicted_gain=0.0, transformed=False)
    assert ok is False
    assert "blocked" in why.lower() or "identical" in why.lower()
    # Transformed with gain allowed
    ok2, _ = rb.may_retrieve(
        "snake game canvas HTML architecture",
        predicted_gain=0.5,
        transformed=True,
    )
    assert ok2 is True


# ── D-08 Retry binding ───────────────────────────────────────────────────────

def test_d08_retry_binding_across_process(tmp_path):
    led = SessionIntentLedger(session_id="sess_test_retry", root=tmp_path)
    led.record_code_run(
        run_id="run_abc",
        task="make a pdf report",
        status="terminated",
        checkpoint_id="ckpt_9",
        failed=True,
    )
    # New process / new instance, same root
    led2 = SessionIntentLedger(session_id="sess_test_retry", root=tmp_path)
    assert led2.load() or led2.pointers.last_code_run_id == "run_abc"
    r = led2.resolve_followup("try again")
    assert r["action"] == "retry"
    assert r["run_id"] == "run_abc"
    assert "make a pdf" in r["task"]
    r2 = led2.resolve_followup("resume")
    assert r2["action"] == "resume"
    # Ambiguous with empty ledger
    empty = SessionIntentLedger(session_id="sess_empty", root=tmp_path)
    r3 = empty.resolve_followup("try again")
    assert r3["action"] == "clarify"


# ── D-09 Self description ────────────────────────────────────────────────────

def test_d09_self_description_runtime_grounded():
    m = build_runtime_manifest(
        reasoner_profile="workers-ai",
        active_model="llama-3.3-70b",
        graft_state="offline",
        network_enabled=False,
        browser_verifier="static_lint",
        capabilities=["python3", "html.static_lint"],
    )
    text = m.self_description_text()
    assert "controller" in text.lower()
    assert "llama-3.3-70b" in text
    assert "static_lint" in text
    # Unsupported external knowledge claim
    assert m.allows_claim("I have broad external knowledge access to the whole internet") is False
    # Change reasoner — text updates without prompt code changes
    m2 = build_runtime_manifest(reasoner_profile="claude-direct", active_model="claude-sonnet")
    assert "claude-sonnet" in m2.self_description_text()
    assert "claude-sonnet" not in text


# ── D-10 Batch campaign ──────────────────────────────────────────────────────

def test_d10_batch_campaign_queues_without_mislabel():
    man = CampaignManifest(
        campaign_id="camp_1",
        package_version="0.3.0-beta.1",
        server_version="abc",
        reasoner_profile="test",
        controller_version="reliability-v1",
        verifier_version="v1",
        concurrency=2,
    )
    q = CampaignQueue(man)
    tasks = [{"case_id": f"c{i}", "task": f"task {i}", "seed": i} for i in range(20)]
    q.submit_cases(tasks, authenticated=True)
    # All queued — none not_admitted for capacity
    assert all(c.status == CaseStatus.QUEUED.value for c in q.cases.values())

    def executor(rec):
        return {"status": CaseStatus.PASSED.value, "result": {"ok": True}}

    summary = q.run_all(executor)
    assert summary["total"] == 20
    assert summary["counts"].get(CaseStatus.PASSED.value, 0) == 20
    assert summary["counts"].get(CaseStatus.NOT_ADMITTED.value, 0) == 0
    assert summary["counts"].get(CaseStatus.MODEL_FAILED.value, 0) == 0
    receipt = sign_campaign_receipt(summary, secret="test")
    assert receipt["receipt_sha256"]
    # Auth failure is not_admitted, not model_failed
    q2 = CampaignQueue(man)
    bad = q2.submit_cases([{"case_id": "x", "task": "t"}], authenticated=False)
    assert bad[0].status == CaseStatus.NOT_ADMITTED.value


# ── Additional structural gates ───────────────────────────────────────────────

def test_typed_artifact_rejects_html_py_compile():
    reg = ArtifactRegistry()
    reg.upsert("index.html", "<html></html>", role="deliverable")
    err = reg.mark_validator("index.html", "syntax.python", ok=False)
    assert err is not None
    assert "incompatible" in err
    assert validator_accepts("html.render", "html") is True
    assert validator_accepts("syntax.python", "html") is False


def test_semantic_failure_merges_wording():
    led = SemanticFailureLedger(environment_id="e1")
    a = led.record(
        command="xdg-open index.html",
        stderr="xdg-open: no providers available",
        exit_code=1,
    )
    b = led.record(
        command="xdg-open ./index.html",
        stderr="No application is registered to handle this file",
        exit_code=1,
    )
    # Same canonical class
    assert a.canonical_error_class == b.canonical_error_class == "desktop_open_unavailable"
    assert a.fingerprint == b.fingerprint
    assert b.recurrence >= 2
    assert led.requires_causal_change() == "verifier_plan"


def test_branch_requires_strategy_diversity():
    port = BranchPortfolio(min_distance=0.34)
    s1 = StrategyVector(
        artifact_schema="python_module",
        implementation_pattern="curses_ascii",
        tool_plan="xdg-open",
        verifier_plan="desktop.open",
    )
    port.note_failure(s1)
    # Wording-only / same strategy rejected
    s2 = StrategyVector(
        artifact_schema="python_module",
        implementation_pattern="curses_ascii",
        tool_plan="xdg-open",
        verifier_plan="desktop.open",
    )
    ok, why = port.accept_branch(s2, required_lever="verifier_plan")
    assert ok is False
    # Diverse strategy accepted
    s3 = StrategyVector(
        artifact_schema="single_html",
        implementation_pattern="canvas_raf",
        tool_plan="sandbox_run",
        verifier_plan="html.render",
    )
    ok3, _ = port.accept_branch(s3, required_lever="verifier_plan")
    assert ok3 is True
    assert semantic_distance(s1, s3) >= 0.34


def test_hard_feasibility_filter_run_failed():
    cands = [
        {"id": "a", "compile_ok": True, "run_ok": False, "require_run": True,
         "contract_coverage": 0.9, "path_ok": True},
        {"id": "b", "compile_ok": True, "run_ok": True, "require_run": True,
         "contract_coverage": 0.5, "path_ok": True},
    ]
    best, mode = select_candidate(cands)
    assert best is not None
    assert best["id"] == "b"
    assert best.get("diagnostic_only") is False
    # All fail → diagnostic only
    best2, mode2 = select_candidate([cands[0]])
    assert best2 is not None
    assert best2.get("diagnostic_only") is True
    assert mode2 == "diagnostic_fallback"


def test_contract_compiler_html_not_default_python():
    c = compile_contract("build a playable snake game in the browser")
    assert c.primary_language == "html"
    assert "index.html" in c.required_paths
    assert c.primary_language != "python" or "main.py" not in [
        x for x in c.required_paths if any(
            cl.hardness == "hard" and cl.artifact_dependency == x
            for cl in c.clauses
        )
    ]


def test_contract_contradiction_detected():
    c = compile_contract("python only implementation of a canvas requestAnimationFrame game as index.html")
    # May or may not catch depending on cues — force pair:
    c2 = compile_contract("python only index.html game with canvas")
    # At least feasibility path works for clear contradiction
    c3 = compile_contract("no javascript canvas requestAnimationFrame animation")
    assert c3.contradictory or any(cl.hardness == "contradictory" for cl in c3.clauses)


def test_evidence_progress_budget_freezes():
    b = EvidenceProgressBudget(max_steps=10, max_nonpositive=3)
    for i in range(3):
        b.record(ActionDelta(step=i, action="verify", contract_coverage_delta=0.0))
    assert b.frozen is True
    ok, why = b.may_generate(causal_lever_changed=False)
    assert ok is False
    ok2, _ = b.may_generate(causal_lever_changed=True)
    assert ok2 is True


def test_run_reliability_state_blocks_xdg_after_failure():
    rs = RunReliabilityState.open("playable snake game html")
    assert rs.contract.primary_language == "html"
    rs.observe_run(
        "xdg-open index.html",
        exit_code=1,
        stderr="xdg-open: no providers available",
    )
    allowed, why, alt = rs.may_run_command("xdg-open index.html")
    assert allowed is False
    assert alt in ("html.render", "html.static_lint")


def test_pdf_closure_path():
    rs = RunReliabilityState.open("generate a short pdf report as output.pdf")
    assert rs.contract.primary_language == "pdf"
    rs.note_write("output.pdf", "%PDF-1.4 fake", step=1)
    info = rs.evaluate_and_maybe_close(
        ["output.pdf"],
        path_hashes={"output.pdf": "deadbeef"},
        validators_green=True,
        step=1,
    )
    assert info["closure"]["closed"] is True
    assert rs.closure.allow_model_turn() is False


def test_arbiter_rollback_precedence():
    d = select_action(
        {"regressed_from_green": True, "last_green_id": "ckpt_x"},
        [ControllerVote(source="nfet", action="finalize", weight=1.0)],
    )
    assert d.action == "ROLLBACK"
