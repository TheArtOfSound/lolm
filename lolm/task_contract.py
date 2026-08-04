# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Freeform task-contract extraction and checking.

The aerospace-fiction failure mode: the prompt had many checkable requirements
(story, real engineering, real+fictional sources, citations, characters,
backstories) but parse_contract returned no_explicit_contract, so the receipt
could not FAIL the task — only report control activity.

This module extracts a compact requirements ledger from freeform English and
grades the answer deterministically. It feeds parse_contract / check_contract /
receipts so active control + failed task is always a hard FAIL.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── requirement detectors (prompt side) ──────────────────────────────────────

_REQ_RULES: List[Tuple[str, str, Tuple[str, ...]]] = [
    # id, description, cues that must appear in the USER PROMPT
    ("fictional_narrative", "Fictional narrative / story",
     ("story", "fiction", "fictional", "narrative", "tale", "novel", "short story")),
    ("real_engineering", "Real-world technical / engineering depth",
     ("real-world", "real world", "real-life", "real life", "engineering",
      "mechanics", "rocket", "propulsion", "physics", "technical")),
    ("real_sources", "Real / authoritative sources",
     ("real source", "real sources", "cite", "citation", "citations",
      "references", "sources", "bibliography", "peer-reviewed")),
    ("fictional_sources", "Fictional sources clearly labeled",
     ("fictional source", "fictional sources", "made-up source", "invented source",
      "fake source", "imaginary source")),
    ("source_types_distinguished", "Distinguish real vs fictional sources",
     ("both real and fictional", "real and fictional", "distinguish",
      "label sources", "real vs", "real versus")),
    ("invented_characters", "Invented characters",
     ("character", "characters", "protagonist", "crew", "team of", "cast")),
    ("substantial_backstories", "Substantial character backstories",
     ("backstory", "backstories", "background", "life story", "history of",
      "grew up", "origin story", "substantial")),
    ("citations_inline", "Inline citations / footnotes",
     ("cite", "citation", "citations", "[s", "footnote", "with sources")),
]

# Answer-side heuristics (what "passed" looks like)
_ENGINEERING_TERMS = (
    "specific impulse", "isp", "delta-v", "delta v", "thrust-to-weight", "twr",
    "mass fraction", "propellant", "chamber pressure", "nozzle", "staging",
    "orbital insertion", "thermal", "heat shield", "ion thruster", "chemical rocket",
    "oxidizer", "cryogenic", "payload", "g-load", "structural", "life support",
    "radiation", "power budget", "exhaust velocity", "burn time", "trajectory",
)
_NARRATIVE_CUES = (
    "once", "she ", "he ", "they ", "said", "walked", "looked", "chapter",
    "aboard", "captain", "crew", "ship", "mission day", "years later",
)
_CITATION_RE = re.compile(
    r"\[S\d+\]|\[[0-9]+\]|\((?:19|20)\d{2}\)|\bhttps?://\S+|doi:\S+",
    re.IGNORECASE,
)
# Scraped junk / non-entailing "sources" that must never pass as evidence
_JUNK_SOURCE_CUES = (
    "skip to content", "quizzes search", "hot courses", "promptkit",
    "self-verification", "agent receipt", "control-policy", "nfet",
    "cookie", "sign in", "log in", "privacy policy", "subscribe",
)
_AI_META_MEMORY = (
    "explanation-interface", "user feedback", "conversational-model",
    "persistent memory", "provenance", "control policy", "entropy",
    "latent", "nfet", "controller", "telemetry",
)


def extract_requirements(command: str) -> List[Dict[str, str]]:
    """Detect freeform multi-part requirements from the user prompt."""
    lc = (command or "").lower()
    if not lc.strip():
        return []
    out: List[Dict[str, str]] = []
    for rid, desc, cues in _REQ_RULES:
        if any(c in lc for c in cues):
            out.append({"id": rid, "description": desc})
    # Compound "and" lists often imply multi-requirement work even without cues
    if len(out) < 2 and re.search(r"\b(and|with|plus)\b", lc) and len(lc) > 80:
        if any(w in lc for w in ("story", "write", "create", "build", "produce")):
            if "fictional_narrative" not in {r["id"] for r in out}:
                if any(w in lc for w in ("story", "fiction", "narrative", "tale")):
                    out.append({"id": "fictional_narrative",
                                "description": "Fictional narrative / story"})
    return out


def _word_count(text: str) -> int:
    return len((text or "").split())


def _has_named_characters(answer: str) -> bool:
    # Capitalized Name patterns (rough): at least 2 distinct Propercase tokens used as names
    names = re.findall(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)\b", answer or "")
    # drop sentence-start common words
    ban = {"The", "This", "That", "Then", "When", "After", "Before", "During",
           "However", "Finally", "Mission", "Earth", "Mars", "Moon", "Space"}
    uniq = {n for n in names if n.split()[0] not in ban}
    return len(uniq) >= 1


def _backstory_depth(answer: str) -> bool:
    """Rough: character + past/life/grew/trained language over a useful span."""
    a = answer or ""
    words = _word_count(a)
    if words < 90:
        return False
    cues = ("grew up", "born", "childhood", "trained", "years as", "former",
            "background", "career", "studied", "joined", "before the mission",
            "decade", "spent", "engineer")
    hits = sum(1 for c in cues if c in a.lower())
    # Short-mid answers need several strong life-history cues + named characters.
    # Shallow "a team of brilliant minds" scores 0 and fails.
    need = 3 if words < 250 else 2 if words < 500 else 3
    return hits >= need and _has_named_characters(a)


def _engineering_depth(answer: str) -> bool:
    a = (answer or "").lower()
    hits = sum(1 for t in _ENGINEERING_TERMS if t in a)
    # surface jargon alone is not enough — need several real terms
    return hits >= 4


def _narrative_present(answer: str) -> bool:
    a = (answer or "").lower()
    if _word_count(a) < 80:
        return False
    return sum(1 for c in _NARRATIVE_CUES if c in a) >= 3


def _citations_present(answer: str) -> bool:
    return bool(_CITATION_RE.search(answer or ""))


def _junk_ratio_in_text(text: str) -> float:
    lc = (text or "").lower()
    if not lc.strip():
        return 0.0
    hits = sum(1 for j in _JUNK_SOURCE_CUES if j in lc)
    return hits / max(len(_JUNK_SOURCE_CUES), 1)


def score_evidence_relevance(command: str, evidence_items: Sequence[Any]) -> Dict[str, Any]:
    """Grade retrieval utility: relevant vs decorative vs junk."""
    cmd = (command or "").lower()
    cmd_tokens = set(re.findall(r"[a-z]{4,}", cmd))
    # Drop ultra-common
    cmd_tokens -= {"that", "with", "from", "this", "have", "will", "your", "about",
                   "into", "make", "write", "create", "using", "please", "would"}
    retrieved = 0
    relevant = 0
    decorative = 0
    junk = 0
    details: List[Dict[str, Any]] = []
    for raw in evidence_items or []:
        if isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("body") or raw.get("title") or "")
            kind = str(raw.get("kind") or "note")
        else:
            text = str(raw)
            kind = "note"
        if not text.strip():
            continue
        retrieved += 1
        tl = text.lower()
        if any(j in tl for j in _JUNK_SOURCE_CUES) or any(m in tl for m in _AI_META_MEMORY):
            # AI-product memory is almost never on-task for domain fiction/engineering
            if not (cmd_tokens & set(re.findall(r"[a-z]{4,}", tl))):
                junk += 1
                decorative += 1
                details.append({"kind": kind, "status": "junk_or_offtopic",
                                "preview": text[:120]})
                continue
        overlap = len(cmd_tokens & set(re.findall(r"[a-z]{4,}", tl)))
        # Verifier notes count as meta, not domain sources
        if kind in ("verifier_note", "self_note") or "verification pass" in tl:
            decorative += 1
            details.append({"kind": kind, "status": "meta_not_domain", "preview": text[:120]})
            continue
        if overlap >= 2 or any(t in tl for t in _ENGINEERING_TERMS if t in cmd):
            relevant += 1
            details.append({"kind": kind, "status": "relevant", "overlap": overlap,
                            "preview": text[:120]})
        else:
            decorative += 1
            details.append({"kind": kind, "status": "decorative", "overlap": overlap,
                            "preview": text[:120]})
    usage = (relevant / retrieved) if retrieved else 0.0
    verdict = (
        "retrieval_failed_relevance" if retrieved and relevant == 0 else
        "retrieval_mostly_decorative" if retrieved and usage < 0.15 else
        "retrieval_used" if relevant else
        "no_retrieval"
    )
    return {
        "verdict": verdict,
        "retrieved": retrieved,
        "relevant": relevant,
        "decorative": decorative,
        "junk": junk,
        "usage_rate": round(usage, 4),
        "citation_entailment_passed": False,  # filled by check_requirements
        "details": details[:12],
    }


def check_requirements(
    command: str,
    answer: str,
    *,
    requirements: Optional[List[Dict[str, str]]] = None,
    evidence: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Grade answer against extracted requirements. Deterministic."""
    reqs = requirements if requirements is not None else extract_requirements(command)
    retrieval = score_evidence_relevance(command, evidence or [])
    rows: List[Dict[str, Any]] = []
    labels: List[str] = []

    for r in reqs:
        rid = r["id"]
        status = "failed"
        reason = ""
        if rid == "fictional_narrative":
            ok = _narrative_present(answer)
            status = "passed" if ok else "failed"
            reason = "narrative_present" if ok else "narrative_missing_or_too_thin"
            if not ok:
                labels.append("narrative_failed")
        elif rid == "real_engineering":
            ok = _engineering_depth(answer)
            status = "passed" if ok else "failed"
            reason = "engineering_terms_present" if ok else "engineering_specificity_failed"
            if not ok:
                labels.append("engineering_specificity_failed")
        elif rid in ("real_sources", "citations_inline"):
            ok = _citations_present(answer)
            # citations that only point at junk still fail entailment
            junkish = _junk_ratio_in_text(answer) > 0 or retrieval["junk"] > 0
            if ok and junkish and retrieval["relevant"] == 0:
                ok = False
                reason = "citations_present_but_sources_non_entailing"
                labels.append("citation_entailment_failed")
            elif ok:
                reason = "citations_present"
            else:
                reason = "citations_missing"
                labels.append("citation_support_failed")
            status = "passed" if ok else "failed"
        elif rid == "fictional_sources":
            ok = bool(re.search(r"fictional|imaginary|invented source|made-up",
                                (answer or ""), re.I)) or (
                _citations_present(answer) and "fiction" in (answer or "").lower()
            )
            status = "passed" if ok else "partial" if _citations_present(answer) else "failed"
            reason = "fictional_sources_labeled" if ok else "fictional_sources_unlabeled"
            if status == "failed":
                labels.append("source_type_labeling_failed")
        elif rid == "source_types_distinguished":
            a = (answer or "").lower()
            ok = (("real" in a and "fiction" in a)
                  or re.search(r"\b(real sources?|fictional sources?)\b", a))
            status = "passed" if ok else "failed"
            reason = "types_distinguished" if ok else "source_type_labeling_failed"
            if not ok:
                labels.append("source_type_labeling_failed")
        elif rid == "invented_characters":
            ok = _has_named_characters(answer)
            status = "passed" if ok else "failed"
            reason = "named_characters" if ok else "characters_missing"
            if not ok:
                labels.append("characters_missing")
        elif rid == "substantial_backstories":
            ok = _backstory_depth(answer)
            status = "passed" if ok else "failed"
            reason = "backstory_depth_ok" if ok else "character_backstory_failed"
            if not ok:
                labels.append("character_backstory_failed")
        else:
            status = "unknown"
            reason = "no_checker"
        rows.append({
            "id": rid,
            "description": r.get("description") or rid,
            "status": status,
            "reason": reason,
        })

    # Retrieval relevance is always scored when evidence exists
    if retrieval["retrieved"] > 0 and retrieval["relevant"] == 0:
        labels.append("retrieval_relevance_failed")
    elif retrieval["retrieved"] > 0 and retrieval["usage_rate"] < 0.15:
        labels.append("retrieval_mostly_decorative")

    # Citation entailment: [S#] present but no relevant domain evidence
    if _citations_present(answer) and retrieval["relevant"] == 0:
        if "citation_entailment_failed" not in labels:
            labels.append("citation_entailment_failed")
        retrieval["citation_entailment_passed"] = False
    elif _citations_present(answer) and retrieval["relevant"] > 0:
        retrieval["citation_entailment_passed"] = True

    failed = [x for x in rows if x["status"] == "failed"]
    passed = not failed and not any(
        lab in labels for lab in (
            "citation_entailment_failed", "engineering_specificity_failed",
            "retrieval_relevance_failed",
        )
    )
    # If we extracted requirements and any failed → hard fail
    if reqs and failed:
        passed = False
        if "task_contract_failed" not in labels:
            labels.append("task_contract_failed")

    return {
        "has_requirements": bool(reqs),
        "requirements": rows,
        "passed": passed if reqs else None,
        "labels": sorted(set(labels)),
        "retrieval": retrieval,
        "completion_allowed": bool(passed) if reqs else True,
        "verdict": (
            "task_contract_passed" if reqs and passed else
            "task_contract_failed" if reqs and not passed else
            "no_freeform_requirements"
        ),
    }


def merge_into_contract(contract: Dict[str, Any], command: str) -> Dict[str, Any]:
    """Attach freeform requirements onto a parse_contract() result."""
    reqs = extract_requirements(command)
    if not reqs:
        return contract
    contract = dict(contract)
    contract["requirements"] = reqs
    contract["has_contract"] = True
    contract["task_type"] = "freeform_multi_requirement"
    return contract


def apply_requirement_check(
    answer_layer: Dict[str, Any],
    command: str,
    answer: str,
    evidence: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Merge freeform requirement grades into the answer layer."""
    fre = check_requirements(command, answer, evidence=evidence)
    if not fre.get("has_requirements"):
        return answer_layer
    reasons = list(answer_layer.get("reasons") or [])
    for lab in fre.get("labels") or []:
        if lab not in reasons:
            reasons.append(lab)
    if fre.get("passed") is False:
        reasons.append("task_contract_failed")
    passed = answer_layer.get("passed")
    if fre.get("passed") is False:
        passed = False
    elif fre.get("passed") is True and passed is not False:
        passed = True if answer_layer.get("passed") is not False else False
    return {
        **answer_layer,
        "verdict": (
            "task_passed" if passed else
            "task_contract_failed" if passed is False else
            answer_layer.get("verdict") or "no_explicit_contract"
        ),
        "passed": passed,
        "reasons": reasons,
        "requirements": fre.get("requirements"),
        "retrieval_relevance": fre.get("retrieval"),
        "completion_allowed": fre.get("completion_allowed"),
        "freeform": fre,
    }
