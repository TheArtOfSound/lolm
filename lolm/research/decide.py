# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The search-decision layer — when LOLM must investigate before answering.

The controller does not search on every prompt (that would be slow and noisy) and
does not answer from stale model memory when the right move is to look it up. This
decides, deterministically and explainably, from:

  * currentness   — does the answer depend on current facts (who/price/version/latest)?
  * task type     — factual lookup vs. reasoning/logic vs. creative
  * uncertainty   — measured U (high uncertainty on a factual claim → search)
  * memory state  — relevant memory missing, or present-but-stale (refresh)
  * explicit ask  — the user asked for latest / real / current / official source

Logic/math tasks VERIFY instead of search; creative tasks do not search. A stale
relevant memory triggers a refresh. The reason is always recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_CURRENT = re.compile(r"\b(current(ly)?|latest|today|now|recent(ly)?|this (year|week|month)|"
                      r"as of|up[- ]?to[- ]?date|real[- ]?time|live|present|"
                      r"price|cost|version|release|update|news|status|who is the|"
                      r"\b20(2[4-9]|[3-9]\d))\b", re.IGNORECASE)
_EXPLICIT = re.compile(r"\b(latest|current|real[- ]?time|up[- ]?to[- ]?date|official (source|docs?|documentation)|"
                       r"right now|as of today|confirm(ed)? by)\b", re.IGNORECASE)
_FACTUAL = re.compile(r"\b(who|what|when|where|which|how many|how much|is the|are the|"
                      r"was the|ceo|president|capital|population|founded|headquarter)\b", re.IGNORECASE)
_MATH_LOGIC = re.compile(r"\b(prove|proof|theorem|equation|derivative|integral|"
                         r"valid(ity)?|logically|fallac|contradiction|step \d|x\^?2|y\^?2|"
                         r"check this proof|is this (argument|reasoning))\b", re.IGNORECASE)
_CREATIVE = re.compile(r"\b(write|compose|draft|imagine|story|poem|scene|fiction|fantasy|"
                       r"screenplay|lyrics|haiku|narrative|dialogue)\b", re.IGNORECASE)


@dataclass
class SearchDecision:
    search: bool
    reason: str
    score: float
    signals: Dict[str, Any] = field(default_factory=dict)
    queries: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"search": self.search, "reason": self.reason,
                "score": round(self.score, 3), "signals": self.signals,
                "queries": self.queries}


def plan_queries(prompt: str, max_q: int = 3) -> List[str]:
    """Turn a prompt into a few focused search queries (deterministic)."""
    p = re.sub(r"\s+", " ", prompt).strip()
    base = re.sub(r"^(please |can you |could you |tell me |i want to know )", "", p, flags=re.IGNORECASE)
    queries = [base[:160]]
    # An "official source" variant when currentness/authority matters.
    if _EXPLICIT.search(p) or _FACTUAL.search(p):
        core = re.sub(r"[?.!]+$", "", base)[:120]
        queries.append(f"{core} official source")
    if _CURRENT.search(p):
        core = re.sub(r"[?.!]+$", "", base)[:120]
        queries.append(f"{core} latest")
    seen, out = set(), []
    for q in queries:
        k = q.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(q.strip())
    return out[:max_q]


def should_search(prompt: str, *, uncertainty: float = 0.0,
                  memory_hits: Optional[List[Dict[str, Any]]] = None,
                  now_ts: Optional[float] = None) -> SearchDecision:
    """Decide whether to search the web before answering this prompt."""
    p = prompt or ""
    memory_hits = memory_hits or []
    currentness = bool(_CURRENT.search(p))
    explicit = bool(_EXPLICIT.search(p))
    factual = bool(_FACTUAL.search(p))
    math_logic = bool(_MATH_LOGIC.search(p))
    creative = bool(_CREATIVE.search(p)) and not (currentness or factual)
    stale_mem = any(h.get("_stale") for h in memory_hits)
    fresh_mem = any((not h.get("_stale")) for h in memory_hits)
    no_mem = len(memory_hits) == 0

    signals = {
        "currentness": currentness, "explicit_latest": explicit, "factual": factual,
        "math_or_logic": math_logic, "creative": creative, "uncertainty": round(uncertainty, 3),
        "memory_hits": len(memory_hits), "stale_memory": stale_mem, "fresh_memory": fresh_mem,
    }

    # 1) Reasoning / logic → verify, never search.
    if math_logic:
        return SearchDecision(False, "reasoning/logic task — the controller should "
                              "verify the steps, not search the web", 0.0, signals)
    # 2) Pure creative → no current facts needed.
    if creative:
        return SearchDecision(False, "creative task with no factual/currentness need — "
                              "no search", 0.0, signals)
    # 3) Relevant memory exists but is stale → refresh from source.
    if stale_mem:
        return SearchDecision(True, "relevant memory is stale — refresh it from a live "
                              "source", 0.85, signals, plan_queries(p))
    # 4) Currentness / explicit latest / factual lookup → search.
    score = (0.5 * currentness + 0.3 * explicit + 0.25 * factual
             + 0.25 * min(1.0, max(0.0, uncertainty) / 2.0) + 0.2 * no_mem)
    if currentness or explicit or factual:
        # …unless fresh memory already covers a non-currentness factual lookup.
        if fresh_mem and not (currentness or explicit):
            return SearchDecision(False, "fresh source-backed memory already covers this — "
                                  "no search needed", round(score, 3), signals)
        why = ("the user asked for current/latest/official information"
               if explicit else "the answer depends on current facts"
               if currentness else "a factual lookup with no fresh local evidence")
        return SearchDecision(True, f"search — {why}", round(min(score, 1.0), 3),
                              signals, plan_queries(p))
    # 5) High measured uncertainty on something factual-ish + no memory.
    if uncertainty >= 1.5 and no_mem:
        return SearchDecision(True, "high measured uncertainty and no local evidence — "
                              "gather sources", round(score, 3), signals, plan_queries(p))
    # 6) Otherwise the model's own knowledge is the right surface.
    return SearchDecision(False, "no currentness signal and no evidence gap — answer from "
                          "model knowledge", round(score, 3), signals)
