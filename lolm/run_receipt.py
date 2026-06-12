# Copyright (c) 2026 Qira LLC. All rights reserved.
# No commercial use, reproduction, hosting, redistribution, derivative
# product, or competing service use is authorized except under a written
# license signed by Qira LLC.
"""Layered run receipts — the honesty core of Qira Agent Vault.

The product risk named in the brief: an app that celebrates any run with
telemetry as a verified success. This module evaluates INDEPENDENT layers
and lets them disagree:

    prompt     was the complete prompt received?     (hash, counts)
    control    did NFET decisions/events occur?      (from the timeline)
    answer     did the output satisfy the contract?  (parsed from the command)
    evidence   were the provided facts used?         (coverage check)
    vault      was the artifact sealed?              (set at seal time)
    integrity  did AEAD + hash checks pass?          (set at verify time)

"Telemetry observed" is not "reasoning success." A vault verified by AEAD
and SHA-256 is not a good answer. The receipt becomes credible only because
it can say both success and failure honestly — its strongest verdict when a
run streams beautifully but misses the user's contract is:

    nfet_activity_observed_but_task_failed
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

# Named failure modes tracked across the product (from the handoff brief).
FAILURE_MODES = (
    "evidence_not_ingested", "meta_reasoning_loop", "evidence_coverage_failure",
    "required_sections_missing", "proof_receipt_missing", "hypothesis_count_failure",
    "duplicate_generation_detected", "unsupported_hypothesis_added",
    "prompt_truncation_suspected", "audit_contract_failed",
    "nfet_activity_observed_but_task_failed",
)


# -- contract parsing ----------------------------------------------------------

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
USE_EXACTLY_RE = re.compile(r"use exactly(?: this format)?[:.]?\s*(.+)", re.IGNORECASE)
N_HYPOTHESES_RE = re.compile(r"\b(?:exactly\s+)?(\d+|one|two|three|four|five)\s+hypothes[ei]s", re.IGNORECASE)
FACT_LINE_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
NO_INTRO_RE = re.compile(r"\bno intro\b", re.IGNORECASE)
WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
DEFAULT_INVENTION_PROBES = ("window", "vent", "tunnel", "hidden door", "trapdoor", "secret passage")


def parse_contract(command: str) -> Dict[str, Any]:
    """Extract explicit, checkable constraints from a command.

    Only what the user literally asked for is enforced — a receipt must never
    invent requirements any more than the model may invent facts.
    """
    contract: Dict[str, Any] = {"has_contract": False}

    sections = [s.strip() for s in SECTION_RE.findall(command)]
    if not sections:
        m = USE_EXACTLY_RE.search(command)
        if m:
            candidates = [p.strip(" .") for p in re.split(r"[,;]| and ", m.group(1)) if p.strip(" .")]
            sections = [c for c in candidates if 0 < len(c.split()) <= 4]
    if sections:
        contract["required_sections"] = sections

    m = N_HYPOTHESES_RE.search(command)
    if m:
        raw = m.group(1).lower()
        contract["exact_hypotheses"] = WORD_NUMS.get(raw) or int(raw)

    if re.search(r"^\s*FACTS?\s*:", command, re.IGNORECASE | re.MULTILINE):
        facts = [text for _, text in FACT_LINE_RE.findall(command)]
        if facts:
            contract["required_facts"] = facts
            contract["forbidden_inventions"] = [
                p for p in DEFAULT_INVENTION_PROBES
                if p not in command.lower()
            ]

    if NO_INTRO_RE.search(command):
        contract["no_intro"] = True

    contract["has_contract"] = any(k for k in contract if k != "has_contract")
    return contract


# -- answer / evidence checking --------------------------------------------------

def _fact_keywords(fact: str) -> List[str]:
    """Distinctive tokens of a fact: numbers, times, proper nouns, long words."""
    words = re.findall(r"[A-Za-z][\w']+|\d[\d:.]*", fact)
    keep = []
    for w in words:
        if re.match(r"\d", w) or (w[0].isupper() and w.lower() not in ("the", "a")) or len(w) >= 6:
            keep.append(w.lower().rstrip(".:"))
    return keep[:4] or [w.lower() for w in words[:2]]


def _max_ngram_repeat(text: str, n: int = 8) -> int:
    words = text.lower().split()
    counts: Dict[str, int] = {}
    best = 0
    for i in range(max(len(words) - n + 1, 0)):
        g = " ".join(words[i:i + n])
        counts[g] = counts.get(g, 0) + 1
        best = max(best, counts[g])
    return best


def check_contract(answer: str, contract: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an answer against a parsed contract. Returns layer verdicts."""
    reasons: List[str] = []
    answer_lower = answer.lower()

    for section in contract.get("required_sections", []):
        if not re.search(r"(^|\n)\s*(##\s*)?" + re.escape(section.lower()), answer_lower):
            reasons.append("required_sections_missing")
            break

    n_expected = contract.get("exact_hypotheses")
    if n_expected:
        block = answer
        m = re.search(r"hypothes[ei]s(.*?)(?=\n##|\Z)", answer, re.IGNORECASE | re.DOTALL)
        if m:
            block = m.group(1)
        found = len(re.findall(r"^\s*(?:\d+\.|[-*•])\s+\S", block, re.MULTILINE))
        if found != n_expected:
            reasons.append("hypothesis_count_failure")

    evidence: Optional[Dict[str, Any]] = None
    facts = contract.get("required_facts")
    if facts:
        omitted = []
        for i, fact in enumerate(facts, 1):
            keywords = _fact_keywords(fact)
            if not any(k in answer_lower for k in keywords):
                omitted.append(i)
        invented = [p for p in contract.get("forbidden_inventions", []) if p in answer_lower]
        evidence = {
            "facts_total": len(facts),
            "facts_covered": len(facts) - len(omitted),
            "facts_omitted": omitted,
            "invented": invented,
            "verdict": ("evidence_covered" if not omitted and not invented
                        else "invented_fact" if invented else "evidence_omitted"),
        }
        if omitted:
            reasons.append("evidence_coverage_failure")
        if invented:
            reasons.append("unsupported_hypothesis_added")

    if contract.get("no_intro"):
        first = answer.strip().splitlines()[0].lower() if answer.strip() else ""
        if re.match(r"(sure|okay|certainly|here is|here's|let me|great question)", first):
            reasons.append("audit_contract_failed")

    if _max_ngram_repeat(answer) >= 3:
        reasons.append("duplicate_generation_detected")

    passed = not reasons
    return {
        "verdict": "task_passed" if passed else "audit_contract_failed",
        "passed": passed,
        "reasons": reasons,
        "evidence": evidence,
    }


# -- the layered receipt ----------------------------------------------------------

def build_receipt(command: str, answer: str, timeline: List[Dict[str, Any]],
                  ended_by: str, profile: str = "task") -> Dict[str, Any]:
    """Assemble the six-layer receipt for a completed run.

    vault/integrity layers start as not_sealed/not_verified; sealing and
    verification update them. Every layer is independent by design.
    """
    control_actions = [t.get("action", {}).get("kind") for t in timeline]
    control_observed = any(k in ("retrieve", "verify", "branch") for k in control_actions)

    contract = parse_contract(command)
    if contract["has_contract"]:
        answer_layer = check_contract(answer, contract)
    else:
        answer_layer = {"verdict": "no_explicit_contract", "passed": None,
                        "reasons": [], "evidence": None}

    warnings: List[str] = []
    if ended_by == "segment_budget":
        # A budget stop is not a confident finish — the brief asks for yellow,
        # not green, here.
        warnings.append("ended_by_budget_not_confidence")

    task_passed = answer_layer["passed"]
    if task_passed is False and control_observed:
        verdict = "nfet_activity_observed_but_task_failed"
    elif task_passed is False:
        verdict = "task_contract_failed"
    elif task_passed and control_observed:
        verdict = "control_visible_and_task_passed"
    elif task_passed:
        verdict = "task_passed"
    else:
        verdict = "control_visible" if control_observed else "no_control_visible"

    return {
        "receipt_schema": "qira.run.receipt.v1",
        "verdict": verdict,
        "control_observed": control_observed,
        "task_contract_passed": task_passed,
        "artifact_integrity_verified": None,   # set by verify
        "reasons": answer_layer["reasons"],
        "warnings": warnings,
        "layers": {
            "prompt": {
                "verdict": "prompt_received",
                "chars": len(command),
                "token_estimate": max(1, len(command) // 4),
                "sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            },
            "control": {
                "verdict": "control_visible" if control_observed else "no_control_visible",
                "actions": [k for k in control_actions if k],
                "ended_by": ended_by,
                "profile": profile,
            },
            "answer": {k: v for k, v in answer_layer.items() if k != "evidence"},
            "evidence": answer_layer["evidence"] or {"verdict": "no_facts_provided"},
            "vault": {"verdict": "not_sealed"},
            "integrity": {"verdict": "not_verified"},
        },
        "limits": (
            "AEAD/hash verification proves artifact integrity and custody only; "
            "it never proves the answer is factually correct."
        ),
    }


def mark_sealed(receipt: Dict[str, Any], env_id: str) -> Dict[str, Any]:
    receipt["layers"]["vault"] = {"verdict": "vault_sealed", "envelope_id": env_id}
    return receipt


def mark_verified(receipt: Dict[str, Any], integrity: Dict[str, Any]) -> Dict[str, Any]:
    ok = bool(integrity.get("aead_authenticated")) and integrity.get("payload_hash_match", True)
    receipt["layers"]["integrity"] = {
        "verdict": "authenticated" if ok else "tamper_detected",
        **integrity,
    }
    receipt["artifact_integrity_verified"] = ok
    return receipt
