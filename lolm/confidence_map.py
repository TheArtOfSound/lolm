# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Measured per-token confidence over an answer — the thing no other agent shows.

Every other assistant gives you words and asks you to trust them. LOLM re-reads
its own answer through the 5-stream graft (surface / latent / regime / gate) and
measures, per token, how uncertain it actually was — then maps that back to the
exact character spans in the answer. The result is a confidence map: the precise
phrases the model was least sure of, derived from its internals, not a prompted
self-report.

This requires the LOLM graft (the per-token gate/regime/entropy signals); a
plain LLM cannot produce it, which is exactly what makes it novel.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Function words carry high entropy for grammatical, not epistemic, reasons —
# a span that is ONLY these is noise, not a meaningful "uncertain claim".
_STOPWORDS = frozenset((
    "a an the and or but of to in on at is are was were be been being has have "
    "had it its as by for with that this these those from into than then so such "
    "which who whom whose will would can could may might must do does did not no "
    "they them their he she his her we our you your i me my").split())


def _is_contentful(fragment: str) -> bool:
    """A span is worth showing only if it holds at least one content word."""
    words = [w.strip(".,;:!?'\"()").lower() for w in fragment.split()]
    words = [w for w in words if w]
    if not words:
        return False
    return any(len(w) >= 4 and w not in _STOPWORDS for w in words)


def confidence_spans(backbone: Any, graft: Any, text: str,
                     z_threshold: float = 0.9, max_spans: int = 6,
                     max_tokens: int = 1024) -> Dict[str, Any]:
    """Return measured low-confidence spans of ``text``.

    {
      "spans": [{"start": int, "end": int, "score": float, "text": str}],
      "mean_entropy": float, "n_tokens": int, "available": bool
    }

    Spans are contiguous runs of tokens whose entropy is notably above this
    answer's own average (z-score >= z_threshold) — relative uncertainty, so it
    adapts to each answer instead of needing absolute tuning.
    """
    empty = {"spans": [], "mean_entropy": None, "n_tokens": 0, "available": False}
    if backbone is None or graft is None or not (text or "").strip():
        return empty
    try:
        from local_ui.claude_reasoner import telemetry_traces_from_text
        traces = telemetry_traces_from_text(backbone, graft, text, max_tokens=max_tokens)
        if not traces:
            return empty
        # char offsets for the SAME tokenization, so spans map back exactly
        enc = backbone.tokenizer(text, return_offsets_mapping=True,
                                 truncation=True, max_length=max_tokens)
        offsets = enc["offset_mapping"]
    except Exception:
        return empty

    n = min(len(traces), len(offsets))
    if n < 4:
        return empty
    ent = [float(traces[i].get("graft_entropy", 0.0)) for i in range(n)]
    # The first 2 tokens have artificially high entropy (little/no preceding
    # context), so they skew the baseline and produce false "uncertain" marks.
    skip = 2
    body = ent[skip:]
    mu = sum(body) / len(body)
    var = sum((e - mu) ** 2 for e in body) / max(len(body) - 1, 1)
    sd = var ** 0.5
    if sd < 1e-6:
        return {"spans": [], "mean_entropy": round(mu, 4), "n_tokens": n, "available": True}

    # mark uncertain tokens (skip the warm-up), merge adjacent (1-token gaps ok)
    flags = [False if i < skip else (ent[i] - mu) / sd >= z_threshold for i in range(n)]
    spans: List[Dict[str, Any]] = []
    i = 0
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        gap = 0
        last = i
        while j < n and (flags[j] or gap < 1):
            if flags[j]:
                last = j
                gap = 0
            else:
                gap += 1
            j += 1
        start = offsets[i][0]
        end = offsets[last][1]
        if end > start:
            zs = [(ent[k] - mu) / sd for k in range(i, last + 1) if flags[k]]
            frag = text[start:end].strip()
            if frag and _is_contentful(frag):
                spans.append({"start": start, "end": end,
                              "score": round(sum(zs) / len(zs), 2) if zs else 0.0,
                              "text": frag[:120]})
        i = j

    spans.sort(key=lambda s: s["score"], reverse=True)
    return {"spans": spans[:max_spans], "mean_entropy": round(mu, 4),
            "n_tokens": n, "available": True}
