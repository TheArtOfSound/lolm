# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Retrieval transparency — prove a retrieved note was USED, not just present.

Complaint #5: "Saying notes were used is not the same as proving useful
retrieval." A receipt that lists evidence count looks grounded even when the
notes were decorative context the answer ignored. This module binds each
retrieved item to the exact final-answer sentences it supports (by content-word
overlap), and reports retrieved-vs-used so a reviewer can see which notes
actually mattered and which were noise.

Pure Python, no model. It never claims a note "helped quality" — only that the
answer's words overlap the note's, which is a checkable, honest signal of use.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List

_STOP = frozenset((
    "a an the and or but of to in on at is are was were be been being has have had "
    "it its as by for with that this these those from into than then so such which "
    "who whom whose will would can could may might must do does did not no they them "
    "their he she his her we our you your i me my one two three about over under more "
    "less most least very also just only into out up down off per each any all some").split())


def _content_words(text: str) -> set:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]+|\$?\d[\d,.]*", (text or "").lower())
    return {w.strip(".,;:!?'\"-") for w in words
            if (w[0].isdigit() or (len(w) >= 4 and w not in _STOP))}


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def evidence_id(row: Dict[str, Any], idx: int) -> str:
    """Stable short id for a retrieved item: kind + content hash."""
    kind = (row.get("kind") or "item")
    h = hashlib.sha256((row.get("text") or "").encode("utf-8")).hexdigest()[:8]
    return f"{kind}:{h}"


def retrieval_support(evidence: List[Dict[str, Any]], answer: str,
                      min_overlap: int = 2) -> Dict[str, Any]:
    """Bind each evidence row to the answer sentences it supports.

    {
      "retrieved": int, "used": int, "decorative": int,
      "items": [{"id","kind","score","snippet","used","supported_sentences":[...]}],
    }
    A row is "used" when at least one answer sentence shares >= min_overlap
    content words with it. "decorative" = retrieved but unused (honest signal that
    the note did not visibly inform the answer).
    """
    sentences = _split_sentences(answer)
    sent_words = [(_content_words(s), s) for s in sentences]
    items: List[Dict[str, Any]] = []
    for idx, row in enumerate(evidence or []):
        ev_words = _content_words(row.get("text", ""))
        supporting: List[Dict[str, Any]] = []
        if ev_words:
            for si, (sw, s) in enumerate(sent_words):
                shared = ev_words & sw
                if len(shared) >= min_overlap:
                    supporting.append({"sentence": si, "snippet": s[:140],
                                       "shared": sorted(shared)[:6],
                                       "overlap": len(shared)})
        supporting.sort(key=lambda x: x["overlap"], reverse=True)
        items.append({
            "id": row.get("id") or evidence_id(row, idx),
            "kind": row.get("kind", "item"),
            "score": (row.get("meta", {}) or {}).get("score", row.get("score")),
            "snippet": (row.get("text", "") or "")[:160],
            "used": bool(supporting),
            "supported_sentences": supporting[:3],
        })
    used = sum(1 for it in items if it["used"])
    return {
        "retrieved": len(items),
        "used": used,
        "decorative": len(items) - used,
        "items": items,
    }
