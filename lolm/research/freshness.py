# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Time-sensitivity scoring — so an answer from memory never *looks* current.

The search gate (decide.py) decides whether to LOOK THINGS UP. This decides
whether, when it did NOT look things up, the answer should carry an honest
freshness warning. The two work together: the gate catches the obvious current
questions; this is the safety net for the ones it misses, so a stale answer is
labelled "from training memory (~early 2026), not live web" instead of being
dressed up by a confident receipt.

`time_sensitivity(prompt)` → {"risk": "high"|"low", "reason": ...}. HIGH = the
answer depends on the current state of a real-world entity/event/market and could
be out of date if answered from the model's weights. LOW = evergreen (math,
how/why explainers, definitions, creative, personal advice) — stable knowledge.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from lolm.research.decide import _CURRENT, _MATH_LOGIC, _CREATIVE

# Who currently holds a role (changes over time).
_ROLE = re.compile(
    r"\bwho(?:\s+\w+){0,2}\s+(?:is|are|leads?|runs?|heads?|won|holds?|owns?)\b.*?"
    r"\b(ceo|president|prime\s+minister|\bpm\b|leader|king|queen|pope|champion|"
    r"winner|governor|mayor|chair|chairman|director|owner|head|founder|boss)\b"
    r"|\bwho is the\b", re.IGNORECASE)
# Did/has an event happened; is something still the case.
_EVENT = re.compile(
    r"\b(is\s+there\s+(?:still|currently|a)|is\s+\w+\s+still|are\s+\w+\s+still|"
    r"did\s+\w+.*\b(happen|win|pass|sign|die|resign|launch|release|end|leave|quit|"
    r"cut|raise|drop|change|announce|approve|reject|ban|recall|buy|acquire)|"
    r"has\s+\w+.*\b(been|happened|ended|launched|died|resigned|won)|"
    r"when\s+(is|was)\s+the\s+(next|last)|who\s+won|still\s+(alive|in\s+office|going\s+on))\b",
    re.IGNORECASE)
# Markets / prices / valuations.
_MARKET = re.compile(
    r"\b(price|stock|share\s+price|market\s+cap|valuation|worth|exchange\s+rate|"
    r"interest\s+rate|how\s+much\s+(is|does|are)|trading\s+at|net\s+worth)\b",
    re.IGNORECASE)
# Real-world events that move fast.
_GEO_EVENT = re.compile(
    r"\b(war|ceasefire|election|sanction|crisis|protest|coup|treaty|summit|"
    r"invasion|conflict|tariff|strike|outbreak|pandemic|recession|layoffs?|"
    r"acquisition|merger|lawsuit|verdict|scandal)\b", re.IGNORECASE)
# Slow-changing real-world facts: usually fine from memory, but can be out of date,
# so they earn an honest "from memory" note rather than a full live search.
_MEDIUM = re.compile(
    r"\b(tallest|largest|biggest|smallest|richest|poorest|most\s+populous|fastest|"
    r"highest|lowest|longest|shortest|oldest|newest|best[-\s]?selling|most\s+popular|"
    r"number\s+one|population\s+of|capital\s+of|how\s+old\s+is|"
    r"how\s+many\s+\w+\s+(are|is)\s+there)\b", re.IGNORECASE)
# Conceptual / evergreen framing — overrides a bare event word.
_EVERGREEN = re.compile(
    r"\b(prove|theorem|calculate|solve|equation|defin(e|ition)|what\s+is\s+a\b|"
    r"how\s+(does|do|to|can|would|should)|why\s+(is|does|do|are)|explain|"
    r"write|compose|poem|story|recipe|tips?\s+for|plan\s+to|should\s+i|"
    r"meaning\s+of|difference\s+between|pros?\s+and\s+cons?|in\s+general)\b",
    re.IGNORECASE)


def _low(reason: str) -> Dict[str, Any]:
    return {"risk": "low", "reason": reason}


def _high(reason: str) -> Dict[str, Any]:
    return {"risk": "high", "reason": reason}


def time_sensitivity(prompt: str) -> Dict[str, Any]:
    p = prompt or ""
    # Reasoning + creative are stable by construction.
    if _MATH_LOGIC.search(p) or _CREATIVE.search(p):
        return _low("reasoning/creative — answer doesn't depend on current facts")

    current = bool(_CURRENT.search(p))
    role = bool(_ROLE.search(p))
    event = bool(_EVENT.search(p))
    market = bool(_MARKET.search(p))
    geo = bool(_GEO_EVENT.search(p))
    evergreen = bool(_EVERGREEN.search(p))

    signals = [n for n, v in (("currentness", current), ("role-holder", role),
                              ("event/status", event), ("market/price", market)) if v]

    # Strong current-state signals override evergreen phrasing
    # ("what's the price of X" is current even with "what is").
    if current or role or event or market:
        return _high("depends on the current state of a real-world "
                     + (", ".join(signals) or "topic"))
    # A geopolitics/event word framed conceptually ("explain how wars start") is evergreen.
    if evergreen:
        return _low("conceptual / explainer — stable knowledge")
    # A bare real-world event reference with no conceptual framing → treat as current.
    if geo:
        return _high("references a fast-moving real-world event")
    # Slow-changing real-world fact — answer from memory, but flag it honestly.
    if _MEDIUM.search(p):
        return {"risk": "medium",
                "reason": "a slow-changing real-world fact that may have changed since training"}
    return _low("not time-bound")


def freshness_notice(prompt: str) -> Dict[str, Any]:
    """The honest banner to attach when a time-sensitive prompt was NOT searched."""
    return {
        "risk": "high",
        "answered_from": "training_memory",
        "knowledge_cutoff": "early 2026",
        "message": ("This answer is from the model's training memory (knowledge to "
                    "~early 2026), not a live web search — for a fast-moving topic it "
                    "may be out of date."),
        "suggestion": "Ask “latest on …” or “what’s going on with …” to search the live web.",
    }
