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

from lolm.verifiers import run_text_verifiers
from lolm.critique import assess as critique_assess

# Named failure modes tracked across the product (from the handoff brief).
FAILURE_MODES = (
    "evidence_not_ingested", "meta_reasoning_loop", "evidence_coverage_failure",
    "required_sections_missing", "proof_receipt_missing", "hypothesis_count_failure",
    "duplicate_generation_detected", "unsupported_hypothesis_added",
    "prompt_truncation_suspected", "audit_contract_failed",
    "nfet_activity_observed_but_task_failed",
    # Added per the multi-surface audit + biggest-complaints memo: a proof layer
    # has to be able to return RED, not just flattering language.
    "math_check_failed", "empty_answer", "ended_by_budget_not_confidence",
)


# -- contract parsing ----------------------------------------------------------

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
USE_EXACTLY_RE = re.compile(r"use exactly(?: this format)?[:.]?\s*(.+)", re.IGNORECASE)
N_HYPOTHESES_RE = re.compile(r"\b(?:exactly\s+)?(\d+|one|two|three|four|five)\s+hypothes[ei]s", re.IGNORECASE)
FACT_LINE_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
NO_INTRO_RE = re.compile(r"\bno intro\b", re.IGNORECASE)
# Word-count contracts: "700-word", "exactly 500 words", "at least 300 words",
# "under 150 words". The audit flagged that these were silently ignored, so an
# answer could be 5x too long and still 'pass'.
WORD_COUNT_RE = re.compile(
    r"\b(at least|at most|no more than|no fewer than|under|over|more than|fewer than|"
    r"exactly|about|around|roughly|up to)?\s*(\d{2,5})[-\s]?words?\b", re.IGNORECASE)
_WC_MIN = {"at least", "no fewer than", "over", "more than"}
_WC_MAX = {"at most", "no more than", "under", "fewer than", "up to"}
_WC_EXACT = {"exactly"}
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

    wc = WORD_COUNT_RE.search(command)
    if wc:
        qual = (wc.group(1) or "").lower().strip()
        count = int(wc.group(2))
        kind = ("min" if qual in _WC_MIN else "max" if qual in _WC_MAX
                else "exact" if qual in _WC_EXACT else "target")
        contract["word_limit"] = {"kind": kind, "count": count}

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

    wl = contract.get("word_limit")
    if wl:
        words = len(answer.split())
        n = wl["count"]
        kind = wl["kind"]
        # Generous tolerance — models rarely hit an exact count, and a false
        # "too long/short" is itself a dishonest receipt. We flag only clear misses.
        ok = True
        if kind == "min":
            ok = words >= n * 0.9
        elif kind == "max":
            ok = words <= n * 1.1
        elif kind == "exact":
            ok = n * 0.8 <= words <= n * 1.2
        else:  # target
            ok = n * 0.6 <= words <= n * 1.5
        if not ok:
            reasons.append("length_requirement_failed")

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
                  ended_by: str, profile: str = "task",
                  model_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Assemble the layered receipt for a completed run.

    vault/integrity layers start as not_sealed/not_verified; sealing and
    verification update them. Every layer is independent by design.

    ``model_info`` (model_requested / model_used / fallback_used /
    fallback_reason) makes the receipt disclose when a requested frontier
    model was actually served by a fallback — so "this was a 70B answer" can
    never be implied when it wasn't. Telemetry is never proof of model.
    """
    control_actions = [t.get("action", {}).get("kind") for t in timeline]
    control_observed = any(k in ("retrieve", "verify", "branch") for k in control_actions)

    mi = model_info or {}
    model_requested = mi.get("model_requested")
    model_used = mi.get("model_used")
    fallback_used = bool(mi.get("fallback_used"))
    fallback_reason = mi.get("fallback_reason")
    quality_warning = (
        f"Fallback Mode: the requested model ({model_requested}) was unavailable "
        f"({fallback_reason}); this answer was produced by {model_used} and quality "
        "may be reduced. This was not a frontier-model result."
    ) if fallback_used else None
    model_layer = {
        "verdict": "fallback_served" if fallback_used else "requested_model_served",
        "model_requested": model_requested,
        "model_used": model_used,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "quality_warning": quality_warning,
    }

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
    if fallback_used:
        warnings.append("fallback_active_quality_may_be_reduced")

    # Deterministic verifiers: re-derive the arithmetic stated in the answer. A
    # wrong total is a first-class RED verdict — no amount of telemetry, control
    # activity, or vault sealing makes a bad number right. This is the sharpest
    # gap every audit named (the "$3,300 vs $1,650" budget error).
    vres = run_text_verifiers(answer)
    math_failed = vres["passed"] is False
    answer_empty = not (answer or "").strip()

    reasons = list(answer_layer["reasons"])
    if math_failed:
        reasons.append("math_check_failed")
        warnings.append("math_check_failed")
    if answer_empty:
        warnings.append("empty_answer")

    # Deterministic answer critique (complaints #2/#3): grades the ANSWER, not the
    # telemetry — math, contract, and the underdetermined-overclaim failure the
    # battery caught (T4 named a culprit when "insufficient evidence" was correct).
    # Also flags a money/logic/date prompt that finished with no verification.
    crit = critique_assess(command, answer,
                           contract={"passed": answer_layer["passed"]},
                           verifiers=vres, control_acted=control_observed)
    overclaimed = bool(crit["overclaim"])
    for lbl in crit["labels"]:
        if lbl not in reasons:
            reasons.append(lbl)
    if overclaimed:
        warnings.append("overclaim_on_underdetermined")
    if "high_stakes_unverified" in crit["labels"]:
        warnings.append("high_stakes_unverified")

    task_passed = answer_layer["passed"]
    # Verdict precedence is NEGATIVE-FIRST: the receipt surfaces the worst honest
    # truth about the run, never the most flattering. Empty output and a wrong
    # number outrank any control-activity verdict.
    if answer_empty:
        verdict = "empty_answer"
    elif math_failed and control_observed:
        verdict = "nfet_activity_observed_but_math_failed"
    elif math_failed:
        verdict = "math_check_failed"
    elif overclaimed:
        verdict = "answer_overclaimed_underdetermined"
    elif task_passed is False and control_observed:
        verdict = "nfet_activity_observed_but_task_failed"
    elif task_passed is False:
        verdict = "task_contract_failed"
    elif task_passed and control_observed:
        verdict = "control_visible_and_task_passed"
    elif task_passed:
        verdict = "task_passed"
    else:
        verdict = "control_visible" if control_observed else "no_control_visible"

    # Red / yellow / green. GREEN is reserved for a real, checkable contract that
    # actually passed on a clean (non-budget, non-fallback) finish. Instrumentation
    # -only, budget-ended, and fallback runs are YELLOW — visible activity is not a
    # quality win. Failures are RED. No dramatic green on vibes.
    RED = {"empty_answer", "math_check_failed", "nfet_activity_observed_but_math_failed",
           "task_contract_failed", "nfet_activity_observed_but_task_failed",
           "answer_overclaimed_underdetermined"}
    if verdict in RED:
        status_color = "red"
    elif task_passed is True and ended_by != "segment_budget" and not fallback_used:
        status_color = "green"
    else:
        status_color = "yellow"

    # Run-mode strip — fallback disclosure must be impossible to miss (audit #10).
    if fallback_used:
        run_mode = "FALLBACK_MODEL"
    elif model_used and re.search(r"llama|70b|claude|groq|cerebras|together|openrouter|gpt",
                                  str(model_used), re.IGNORECASE):
        run_mode = "LIVE_NFET_FRONTIER"
    else:
        run_mode = "LOCAL_MONITOR"

    # The receipt states its own ceiling: a live run runs no controlled A/B, so it
    # NEVER proves the answer beat a baseline. This blocks proof inflation.
    quality_claim = "unproven_vs_baseline"

    return {
        "receipt_schema": "qira.run.receipt.v1",
        "verdict": verdict,
        "status_color": status_color,
        "run_mode": run_mode,
        "quality_claim": quality_claim,
        "control_observed": control_observed,
        "task_contract_passed": task_passed,
        "math_checks": {"checked": vres["checked"], "failed": vres["failed"],
                        "passed": vres["passed"]},
        "risk_profile": crit["risk_profile"],
        "model_used": model_used,
        "fallback_used": fallback_used,
        "quality_warning": quality_warning,
        "artifact_integrity_verified": None,   # set by verify
        "reasons": reasons,
        "warnings": warnings,
        "layers": {
            "model": model_layer,
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
            "verifiers": {
                "verdict": ("math_check_failed" if math_failed
                            else "no_math_to_check" if vres["checked"] == 0
                            else "math_ok"),
                "checked": vres["checked"], "failed": vres["failed"],
                "checks": vres["checks"],
            },
            "critique": {
                "verdict": crit["verdict"],
                "plain": crit["plain"],
                "math": crit["math"],
                "contract": crit["contract"],
                "overclaim": crit["overclaim"],
                "audit_expected": crit["audit_expected"],
                "audit_satisfied": crit["audit_satisfied"],
                "labels": crit["labels"],
            },
            "vault": {"verdict": "not_sealed"},
            "integrity": {"verdict": "not_verified"},
        },
        "limits": (
            "AEAD/hash verification proves artifact integrity and custody only; it "
            "never proves the answer is factually correct. A live receipt runs no "
            "baseline A/B, so quality stays unproven_vs_baseline."
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
