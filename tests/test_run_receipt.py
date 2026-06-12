from __future__ import annotations

from lolm.run_receipt import build_receipt, check_contract, mark_sealed, mark_verified, parse_contract

SEALED_ROOM = """Use exactly this format. No intro.

FACTS:
1. Keypad accepted valid code at 09:13:06.
2. Door opened at 09:13:08.
3. Mass increased by 71.4 kg at 09:13:09.
4. Camera shows nobody entering from 09:12 to 09:15.
5. Alice knows the code.
6. Bob was near the building but does not know the code.

## Timeline
## Contradiction
## Three Hypotheses
## Conclusion
## Proof Receipt

Rules:
- Mention all 6 facts.
- Do not invent windows, vents, tunnels, or hidden facts.
- Do not name a culprit."""

GOOD_ANSWER = """## Timeline
09:13:06 keypad accepted the valid code; 09:13:08 the door opened; 09:13:09 mass increased by 71.4 kg; the camera shows nobody entering 09:12-09:15.

## Contradiction
Keypad, door and mass suggest entry while the camera shows none. Alice knows the code; Bob was near the building but does not know the code.

## Three Hypotheses
1. Sensor clock skew produced a phantom entry record.
2. The camera missed a real entry due to coverage angle.
3. The mass sensor registered an object, not a person.

## Conclusion
No culprit can be identified from the facts alone.

## Proof Receipt
All six facts considered; no entities invented."""


def test_contract_parsed_from_sealed_room():
    c = parse_contract(SEALED_ROOM)
    assert c["has_contract"]
    assert c["required_sections"] == ["Timeline", "Contradiction", "Three Hypotheses",
                                      "Conclusion", "Proof Receipt"]
    assert c["exact_hypotheses"] == 3
    assert len(c["required_facts"]) == 6
    assert c["no_intro"] is True
    # the command names windows/vents/tunnels in its RULES, so they are not probes
    assert "window" not in c["forbidden_inventions"]


def test_good_answer_passes_contract():
    result = check_contract(GOOD_ANSWER, parse_contract(SEALED_ROOM))
    assert result["passed"], result["reasons"]
    assert result["evidence"]["verdict"] == "evidence_covered"
    assert result["evidence"]["facts_covered"] == 6


def test_missing_section_and_facts_fail_honestly():
    bad = "Some meta-analysis of the case without the requested structure. Alice did it."
    result = check_contract(bad, parse_contract(SEALED_ROOM))
    assert not result["passed"]
    assert "required_sections_missing" in result["reasons"]
    assert "evidence_coverage_failure" in result["reasons"]


def test_hypothesis_count_enforced():
    two_only = GOOD_ANSWER.replace(
        "3. The mass sensor registered an object, not a person.\n", "")
    result = check_contract(two_only, parse_contract(SEALED_ROOM))
    assert "hypothesis_count_failure" in result["reasons"]


def test_duplicate_generation_detected():
    dup = ("## Timeline\n" + ("the same eight word phrase repeats again and again " * 3) +
           "\n## Contradiction\nx\n## Three Hypotheses\n1. a\n2. b\n3. c\n## Conclusion\nx\n## Proof Receipt\nall facts 09:13:06 09:13:08 71.4 camera Alice Bob")
    result = check_contract(dup, parse_contract(SEALED_ROOM))
    assert "duplicate_generation_detected" in result["reasons"]


def test_flagship_verdict_activity_observed_but_task_failed():
    """The brief's core honesty case: beautiful telemetry, failed contract."""
    timeline = [{"action": {"kind": "retrieve"}}, {"action": {"kind": "continue"}}]
    receipt = build_receipt(SEALED_ROOM, "a rambling answer with no structure",
                            timeline, ended_by="nfet_finalize")
    assert receipt["verdict"] == "nfet_activity_observed_but_task_failed"
    assert receipt["control_observed"] is True
    assert receipt["task_contract_passed"] is False
    assert receipt["layers"]["answer"]["verdict"] == "audit_contract_failed"
    assert receipt["layers"]["vault"]["verdict"] == "not_sealed"


def test_no_contract_runs_stay_unjudged():
    receipt = build_receipt("why is the sky blue?", "Rayleigh scattering.",
                            [{"action": {"kind": "continue"}}], ended_by="nfet_finalize")
    assert receipt["task_contract_passed"] is None
    assert receipt["layers"]["answer"]["verdict"] == "no_explicit_contract"
    assert receipt["verdict"] == "no_control_visible"


def test_budget_ending_is_a_warning_not_a_pass():
    receipt = build_receipt("why?", "Because.", [], ended_by="segment_budget")
    assert "ended_by_budget_not_confidence" in receipt["warnings"]


def test_seal_and_verify_marks():
    receipt = build_receipt("why?", "Because.", [], ended_by="nfet_finalize")
    mark_sealed(receipt, "abc123")
    assert receipt["layers"]["vault"]["verdict"] == "vault_sealed"
    mark_verified(receipt, {"aead_authenticated": True, "payload_hash_match": True})
    assert receipt["artifact_integrity_verified"] is True
    assert receipt["layers"]["integrity"]["verdict"] == "authenticated"
    mark_verified(receipt, {"aead_authenticated": True, "payload_hash_match": False})
    assert receipt["artifact_integrity_verified"] is False
    assert receipt["layers"]["integrity"]["verdict"] == "tamper_detected"
