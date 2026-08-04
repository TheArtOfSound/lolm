# Copyright (c) 2026 Qira LLC. All rights reserved.
"""T10-style freeform contract: aerospace fiction must FAIL when shallow."""

from lolm.task_contract import (
    check_requirements,
    extract_requirements,
    score_evidence_relevance,
)
from lolm.run_receipt import build_receipt, parse_contract


AERO_PROMPT = (
    "Write a fictional story about a crewed Mars mission that uses real-life "
    "rocket mechanics and engineering. Cite both real and fictional sources, "
    "clearly distinguish them, invent characters with substantial backstories."
)

SHALLOW = (
    "Rachel Kim led a team of brilliant minds aboard the Odyssey. "
    "The spacecraft used a combination of liquid fuel and ion thrusters "
    "to achieve unprecedented speeds and efficiency [S1][S2][S3]. "
    "Challenges included navigation and life support [S4]. "
    "They landed safely on Mars and planted a flag."
)

# Deliberately non-entailing "sources" (like the failed run)
JUNK_EVIDENCE = [
    {"kind": "note", "text": "PromptKit self-verification GitHub page for AI agents"},
    {"kind": "note", "text": "Skip to Content Quizzes Search PRO Courses Hot"},
    {"kind": "note", "text": "wikiHow: difference between fiction and nonfiction"},
    {"kind": "verifier_note", "text": "A verification pass flagged the draft: too little engineering"},
    {"kind": "note", "text": "NFET control-policy calibration and user feedback notes"},
]


def test_extracts_aerospace_fiction_requirements():
    reqs = extract_requirements(AERO_PROMPT)
    ids = {r["id"] for r in reqs}
    assert "fictional_narrative" in ids
    assert "real_engineering" in ids
    assert "invented_characters" in ids or "substantial_backstories" in ids
    assert "real_sources" in ids or "citations_inline" in ids
    assert len(reqs) >= 4


def test_parse_contract_no_longer_empty_for_freeform():
    c = parse_contract(AERO_PROMPT)
    assert c["has_contract"] is True
    assert c.get("requirements")


def test_shallow_aerospace_answer_fails_contract():
    fre = check_requirements(AERO_PROMPT, SHALLOW, evidence=JUNK_EVIDENCE)
    assert fre["has_requirements"]
    assert fre["passed"] is False
    assert fre["completion_allowed"] is False
    assert "task_contract_failed" in fre["labels"] or any(
        r["status"] == "failed" for r in fre["requirements"]
    )
    # Engineering depth and backstories should fail
    by_id = {r["id"]: r for r in fre["requirements"]}
    if "real_engineering" in by_id:
        assert by_id["real_engineering"]["status"] == "failed"
    if "substantial_backstories" in by_id:
        assert by_id["substantial_backstories"]["status"] == "failed"


def test_retrieval_relevance_marks_junk_and_meta():
    rep = score_evidence_relevance(AERO_PROMPT, JUNK_EVIDENCE)
    assert rep["retrieved"] >= 4
    assert rep["relevant"] == 0
    assert rep["verdict"] in (
        "retrieval_failed_relevance", "retrieval_mostly_decorative",
    )


def test_receipt_is_red_fail_active_control_failed_contract():
    timeline = [
        {"action": {"kind": "retrieve", "added": 5}},
        {"action": {"kind": "verify", "verdict": "revise"}},
        {"action": {"kind": "retrieve", "added": 3}},
        {"action": {"kind": "finalize"}},
    ]
    r = build_receipt(
        AERO_PROMPT, SHALLOW, timeline, "draft_cap_finalize",
        profile="task",
        retrieval={"retrieved": 47, "used": 1, "decorative": 46,
                   "items": JUNK_EVIDENCE},
    )
    assert r["status_color"] == "red"
    assert r["verdict"] in (
        "nfet_activity_observed_but_task_failed", "task_contract_failed",
    )
    assert r["task_contract_passed"] is False
    assert r["layers"]["answer"]["passed"] is False
    # Must not claim no_explicit_contract
    assert r["layers"]["answer"]["verdict"] != "no_explicit_contract"
    ret = r["layers"]["retrieval"]
    assert ret.get("verdict") in (
        "retrieval_failed_relevance", "retrieval_mostly_decorative",
        "retrieval_used", "retrieval_decorative",
    )
    # Critique must not say no deterministic fault
    crit = r["layers"].get("critique") or {}
    if crit:
        assert crit.get("verdict") != "answer_no_deterministic_fault" or r["status_color"] == "red"


def test_post_revision_style_failures_listed():
    fre = check_requirements(AERO_PROMPT, SHALLOW, evidence=JUNK_EVIDENCE)
    assert fre["completion_allowed"] is False
    fails = [r["id"] for r in fre["requirements"] if r["status"] == "failed"]
    assert "real_engineering" in fails or "substantial_backstories" in fails


def test_receipt_stage_pre_seal_and_mark_sealed():
    from lolm.run_receipt import mark_sealed, mark_verified
    r = build_receipt(AERO_PROMPT, SHALLOW, [], "contract_incomplete")
    assert r.get("receipt_stage") == "pre_seal"
    assert r["layers"]["vault"]["verdict"] == "not_sealed"
    mark_sealed(r, "env-test-1")
    assert r["receipt_stage"] == "post_seal"
    assert r["envelope_integrity"]["sealed"] is True
    assert r["layers"]["vault"]["verdict"] == "vault_sealed"
    mark_verified(r, {"aead_authenticated": True, "payload_hash_match": True,
                      "algorithm": "test"})
    assert r["envelope_integrity"]["verified"] is True
    assert r["receipt_stage"] == "post_seal_verified"


def test_deep_engineering_snippet_can_pass_engineering_axis():
    deep = (
        "Captain Mara Okonkwo grew up in Lagos and trained as a propulsion engineer "
        "at MIT before joining the Mars program. Her co-pilot, Leo Sato, spent a decade "
        "on cryogenic feed systems after a childhood in Hokkaido watching rockets from Tanegashima. "
        "The vehicle used a kerosene/LOX first stage for high thrust-to-weight at liftoff, "
        "then a high-Isp ion thruster stage for in-space delta-v once solar arrays provided power. "
        "They budgeted propellant mass fraction carefully, managed chamber pressure, and "
        "designed the nozzle expansion for vacuum. Thermal management and radiation shielding "
        "drove structural mass. Real sources: NASA SP-2009-566; fictional: Chronicles of Ares (2124). "
        "[S1][S2]"
    )
    fre = check_requirements(AERO_PROMPT, deep, evidence=[
        {"kind": "note", "text": "NASA technical report on chemical rocket specific impulse and staging"},
        {"kind": "note", "text": "Ion thruster power requirements and exhaust velocity for deep space"},
    ])
    by_id = {r["id"]: r for r in fre["requirements"]}
    if "real_engineering" in by_id:
        assert by_id["real_engineering"]["status"] == "passed"
    if "substantial_backstories" in by_id:
        assert by_id["substantial_backstories"]["status"] == "passed"
