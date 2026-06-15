# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The research pipeline — investigate, read, learn, and prove what changed.

  retrieve memory → decide(search?) → plan queries → search → rank sources
  → open top sources → extract claims → answer (grounded) → judge what was USED
  → write source-backed memory → honest receipt

The receipt is brutal about provenance: retrieved ≠ opened ≠ used. If sources were
fetched but did not materially change the answer, the receipt says so
("Retrieved N. 0 materially changed the answer. Retrieval did not improve this
run."). Nothing here claims a source helped when it did not.

search_fn / fetch_fn / answer_fn are injected so this is fully testable offline;
in production they are local_ui.internet_tools.web_search / fetch_url and the 70B
grounded finalizer.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from lolm.research.decide import should_search, SearchDecision
from lolm.research.memory import ResearchMemory, ResearchMemoryStore, source_quality

SearchFn = Callable[[str, int], Dict[str, Any]]
FetchFn = Callable[[str], Dict[str, Any]]
# answer_fn(prompt, sources, memories) -> answer text
AnswerFn = Callable[[str, List[Dict[str, Any]], List[Dict[str, Any]]], str]


def unwrap_url(url: str) -> str:
    """DuckDuckGo wraps results as //duckduckgo.com/l/?uddg=<encoded>. Unwrap it."""
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    p = urlparse(url)
    if "duckduckgo.com" in (p.hostname or "") and p.path.startswith("/l"):
        q = parse_qs(p.query)
        if q.get("uddg"):
            return unquote(q["uddg"][0])
    return url


def _toks(s: str) -> set:
    return {w for w in re.split(r"\W+", (s or "").lower()) if len(w) > 3}


def _best_sentence(text: str, query: str, limit: int = 320) -> str:
    sents = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text or "").strip())
    q = _toks(query)
    best, score = "", -1
    for s in sents[:400]:
        if len(s) < 20:
            continue
        ov = len(q & _toks(s))
        if ov > score:
            best, score = s, ov
    return best[:limit]


@dataclass
class ResearchPipeline:
    memory_store: ResearchMemoryStore
    answer_fn: AnswerFn
    search_fn: Optional[SearchFn] = None
    fetch_fn: Optional[FetchFn] = None
    max_sources: int = 3
    memory_write: bool = True

    def run(self, prompt: str, *, uncertainty: float = 0.0,
            run_id: Optional[str] = None, allow_web: bool = True,
            force: bool = False) -> Dict[str, Any]:
        run_id = run_id or f"research-{uuid.uuid4().hex[:12]}"
        actions: List[Dict[str, Any]] = []
        step = [0]

        def act(action: str, reason: str, **extra) -> None:
            step[0] += 1
            actions.append({"step": step[0], "action": action, "reason": reason, **extra})

        # 1) Local source-backed memory first.
        mem_hits = self.memory_store.retrieve(prompt, limit=5)
        if mem_hits:
            act("retrieve_local_memory", "check what we already learned",
                count=len(mem_hits), stale=sum(1 for m in mem_hits if m.get("_stale")))

        # 2) Decide. `force` = always-on web mode: search every prompt regardless.
        decision = should_search(prompt, uncertainty=uncertainty, memory_hits=mem_hits)
        reason = ("always-on web mode — searching every prompt"
                  if force and not decision.search else decision.reason)
        act("search_decision", reason, search=decision.search or force,
            signals=decision.signals, forced=bool(force and not decision.search))

        retrieved: List[Dict[str, Any]] = []
        opened: List[Dict[str, Any]] = []
        written: List[str] = []
        mode = "model_only"

        do_search = (decision.search or force) and allow_web and self.search_fn is not None
        if decision.search and not do_search:
            act("search_skipped", "search indicated but web is disabled or no provider — "
                "answering without it (disclosed)")

        if do_search:
            mode = "live_web_research"
            for q in (decision.queries or [prompt])[:3]:
                act("search_web", "current/factual claim needs evidence", query=q)
                try:
                    res = self.search_fn(q, 6) or {}
                except Exception as exc:
                    act("search_error", str(exc)[:120]); continue
                for r in (res.get("results") or []):
                    retrieved.append({"title": r.get("title", ""),
                                      "url": unwrap_url(r.get("url", "")),
                                      "snippet": r.get("snippet", ""), "query": q,
                                      "provider": res.get("provider")})
            # 3) Rank + open the top sources.
            ranked = self._rank(retrieved, prompt)
            for r in ranked[: self.max_sources]:
                act("open_source", "primary/high-quality source preferred",
                    url=r["url"], quality=source_quality(r["url"]))
                text, title = r.get("snippet", ""), r.get("title", "")
                if self.fetch_fn is not None:
                    try:
                        f = self.fetch_fn(r["url"]) or {}
                        text = f.get("text") or text
                        title = f.get("title") or title
                    except Exception as exc:
                        act("fetch_error", str(exc)[:120])
                claim = _best_sentence(text, prompt) or r.get("snippet", "")
                opened.append({**r, "title": title, "claim": claim,
                               "excerpt": (text or "")[:1600],
                               "quality": source_quality(r["url"])})

        # 4) Answer (grounded in opened sources + fresh memories).
        answer = self.answer_fn(prompt, opened, [m for m in mem_hits if not m.get("_stale")])
        if mode == "model_only" and mem_hits:
            mode = "memory_grounded"
        act("answer_from_model" if mode == "model_only" else "answer_grounded",
            "compose the final answer from the available evidence")

        # 5) Judge what was actually USED (materially) vs ignored/decorative.
        a_toks = _toks(answer)
        used, ignored = [], []
        for s in opened:
            ct = _toks(s.get("claim") or s.get("snippet") or "")
            overlap = len(ct & a_toks) / max(len(ct), 1)
            (used if overlap >= 0.2 else ignored).append({**s, "overlap": round(overlap, 3)})
        mem_used = []
        for m in mem_hits:
            mt = _toks(m.get("claim", "") + " " + m.get("summary", ""))
            if len(mt & a_toks) / max(len(mt), 1) >= 0.2 and not m.get("_stale"):
                mem_used.append(m)
                self.memory_store.record_use(m["memory_id"], run_id)

        # 6) Learn: write a source-backed memory for a used finding.
        if self.memory_write and used:
            top = used[0]
            mem = ResearchMemory(
                topic=prompt[:80], claim=top.get("claim", "")[:300],
                summary=_best_sentence(answer, prompt), source_urls=[top["url"]],
                source_titles=[top.get("title", "")], confidence=0.7,
                used_in_runs=[run_id], tags=_query_tags(prompt))
            written.append(self.memory_store.write(mem))
            act("write_memory", "source-backed current finding worth reusing",
                memory_id=written[-1])

        # 7) Honest verdict.
        searched = mode == "live_web_research"
        if searched and used:
            verdict = (f"Searched the web; {len(used)} of {len(opened)} opened source(s) "
                       f"materially shaped the answer. Wrote {len(written)} memory.")
            improved = True
        elif searched and not retrieved:
            verdict = ("Searched the web but found no usable results for these queries; "
                       "answered without sources (disclosed). Search did not improve this run.")
            improved = False
        elif searched and not opened:
            verdict = (f"Searched and retrieved {len(retrieved)} result(s) but opened none "
                       "successfully; answered without them (disclosed).")
            improved = False
        elif searched and opened and not used:
            verdict = (f"Retrieved {len(retrieved)} result(s), opened {len(opened)}. "
                       "0 materially changed the final answer. Retrieval did not improve "
                       "this run.")
            improved = False
        elif mem_used:
            verdict = (f"Answered from {len(mem_used)} source-backed memory(ies); no web "
                       "search needed.")
            improved = True
        else:
            verdict = ("Answered from model knowledge — no currentness signal or evidence "
                       "gap, so no search.")
            improved = None

        return {
            "run_id": run_id, "prompt": prompt, "answer": answer, "mode": mode,
            "controller_active": True,
            "search_decision": decision.to_dict(),
            "actions": actions,
            "sources": {
                "retrieved": retrieved, "opened": opened, "used": used, "ignored": ignored,
            },
            "memories": {
                "retrieved": mem_hits, "used": mem_used, "written": written,
                "stale_detected": [m["memory_id"] for m in mem_hits if m.get("_stale")],
            },
            "verdict": verdict,
            "answer_improved_by_research": improved,
        }

    def _rank(self, results: List[Dict[str, Any]], prompt: str) -> List[Dict[str, Any]]:
        q = _toks(prompt)
        qual = {"high": 1.5, "medium": 1.0, "low": 0.5}
        seen, uniq = set(), []
        for r in results:
            u = r.get("url", "")
            if u and u not in seen:
                seen.add(u); uniq.append(r)
        return sorted(uniq, key=lambda r: (
            qual.get(source_quality(r.get("url", "")), 1.0)
            * (1 + len(q & _toks(r.get("title", "") + " " + r.get("snippet", ""))))
        ), reverse=True)


def _query_tags(prompt: str) -> List[str]:
    return [w for w in re.split(r"\W+", prompt.lower()) if len(w) > 4][:6]
