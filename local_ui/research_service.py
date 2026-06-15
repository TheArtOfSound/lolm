# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Live research service — wires the research pipeline to real providers.

search  = local_ui.internet_tools.web_search  (Brave/Tavily/SearxNG/DuckDuckGo keyless)
fetch   = local_ui.internet_tools.fetch_url    (SSRF-safe)
answer  = the frontier 70B, grounded ONLY in the opened sources + fresh memories,
          citing the source tag for every claim and refusing when the sources do
          not contain the answer.

Exposes POST /api/demo/research and GET /api/demo/research/memory (stats + recent),
both rate-limited by the existing demo gate so the public endpoint can't be abused.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request
from pydantic import BaseModel

from local_ui import internet_tools
from lolm.research.memory import ResearchMemoryStore
from lolm.research.pipeline import ResearchPipeline


class ResearchRequest(BaseModel):
    command: str


class JobRequest(BaseModel):
    job_id: str

RESEARCH_MEMORY_PATH = Path(os.environ.get(
    "RESEARCH_MEMORY_PATH",
    str(Path(__file__).resolve().parents[1] / "runs" / "research_memory.jsonl")))

GROUNDED_SYSTEM = (
    "You are LOLM's research answerer. Use the SOURCES to answer the QUESTION, "
    "synthesizing across them. If a source identifies the person or fact currently "
    "filling a role (e.g. names a CEO or president, or states a version/price), "
    "ANSWER with it and cite the source — treat the most authoritative / most recent "
    "source as current unless another source contradicts it. Cite [S#] or [M#] after "
    "each claim. Say 'The sources I found do not confirm this' ONLY when no source "
    "addresses the question at all. Never invent facts beyond the sources. Be direct "
    "and concise; lead with the answer."
)

# When the controller decided NOT to search (logic, math, creative, or a fact the
# model knows), answer from the model's own reasoning — a research-grounded
# 'no sources' refusal would be wrong here.
DIRECT_SYSTEM = (
    "You are a careful, accurate assistant. Answer the QUESTION directly and "
    "correctly. If it is a math or logic proof, check each step and give a concrete "
    "counterexample when a step is invalid. Be concise and specific."
)


def make_research_pipeline(frontier_loop: Callable, ChatRequest: Any, ChatMessage: Any,
                           memory_path: Optional[Path] = None,
                           max_sources: int = 5) -> ResearchPipeline:
    store = ResearchMemoryStore(memory_path or RESEARCH_MEMORY_PATH)

    def frontier_chat(messages: List[Any]) -> str:
        try:
            req = ChatRequest(messages=messages, max_new_tokens=700, temperature=0.2,
                              top_p=0.9, use_graft=False)
        except TypeError:
            req = ChatRequest(messages=messages, max_new_tokens=700, temperature=0.2,
                              top_p=0.9, use_graft=False)
        try:
            req.telemeter = False
        except Exception:
            pass
        text = ""
        for ev in frontier_loop(req):
            if ev.get("event") == "done":
                text = (ev.get("data") or {}).get("response", "") or text
            elif ev.get("event") == "error":
                raise RuntimeError((ev.get("data") or {}).get("error", "frontier error"))
        return text.strip()

    def answer_fn(prompt: str, sources: List[Dict[str, Any]],
                  memories: List[Dict[str, Any]]) -> str:
        # No evidence gathered (controller chose not to search) → answer directly
        # from the model's own reasoning rather than refuse for lack of sources.
        if not sources and not memories:
            return frontier_chat([ChatMessage(role="system", content=DIRECT_SYSTEM),
                                   ChatMessage(role="user", content=f"QUESTION:\n{prompt}")])
        blocks: List[str] = []
        for i, s in enumerate(sources, 1):
            body = (s.get("excerpt") or s.get("claim") or s.get("snippet") or "")[:1400]
            blocks.append(f"[S{i}] {s.get('title', '')} — {s.get('url', '')}\n{body}")
        for i, m in enumerate(memories, 1):
            srcs = ", ".join(m.get("source_urls") or [])
            blocks.append(f"[M{i}] (source-backed memory; {srcs}) {m.get('claim', '')}")
        user = (f"QUESTION:\n{prompt}\n\nSOURCES:\n"
                + ("\n\n".join(blocks) if blocks else "(no sources retrieved)"))
        return frontier_chat([ChatMessage(role="system", content=GROUNDED_SYSTEM),
                              ChatMessage(role="user", content=user)])

    return ResearchPipeline(
        memory_store=store, answer_fn=answer_fn,
        search_fn=internet_tools.web_search, fetch_fn=internet_tools.fetch_url,
        max_sources=max_sources)


def web_route_events(pipeline: ResearchPipeline, command: str):
    """If a prompt needs CURRENT facts, run real web research and yield it as the
    main demo's SSE event protocol so the landing-page agent actually searches —
    not just the Research tab. Returns None when no live search is warranted, so
    the caller falls through to the normal NFET control theater (math, logic,
    general knowledge keep the per-token uncertainty graph).

    Gate is deliberately tight: only currentness ("today/latest/current/news/
    price/2025…") or an explicit ask for current/official info diverts here. A
    plain factual or arithmetic prompt does NOT get web-routed."""
    import re as _re
    from lolm.research.decide import should_search

    dec = should_search(command)
    sig = dec.signals or {}
    if not (dec.search and (sig.get("currentness") or sig.get("explicit_latest"))):
        return None

    def gen():
        yield {"event": "run_start", "data": {"head_trained": False, "mode": "web_research"}}
        yield {"event": "decision", "data": {"segment": 1, "decision": {
            "label": "retrieve", "source": "search", "reason": dec.reason, "zscores": {}}}}
        yield {"event": "phase", "data": {"phase": "finalize"}}
        try:
            result = pipeline.run(command, allow_web=True)
        except Exception as exc:
            yield {"event": "error", "data": {"error": f"web research failed: {exc}"[:200]}}
            return
        s = result.get("sources") or {}
        used = s.get("used") or []
        yield {"event": "action", "data": {"segment": 1, "kind": "retrieve", "added": len(used)}}
        for tok in _re.findall(r"\S+\s*", result.get("answer") or "(no answer)"):
            yield {"event": "token", "data": {"channel": "final", "token": tok}}
        cites = " · ".join(f"[S{i+1}] {(u.get('title') or u.get('url') or '')[:48]}"
                           for i, u in enumerate(used[:4])) or "no sources materially used"
        yield {"event": "proof", "data": {
            "verdict": result.get("verdict", ""), "plain": "Sources: " + cites,
            "control_counts": {"web_search": 1, "sources_used": len(used)},
            "decision_sources": {"web": len(used),
                                 "retrieved": len(s.get("retrieved") or []),
                                 "opened": len(s.get("opened") or [])},
            "ended_by": "web_search"}}
        yield {"event": "run_done", "data": {}}
    return gen()


def register_research_routes(app: Any, pipeline: ResearchPipeline,
                             gate: Optional[Any] = None,
                             scheduler: Optional[Any] = None) -> None:

    @app.post("/api/demo/research")
    def research(req: ResearchRequest):
        cmd = (req.command or "").strip()[:2000]
        if not cmd:
            return {"error": "empty command"}
        if gate is not None and hasattr(gate, "check_rate"):
            ok, msg = gate.check_rate("research")
            if not ok:
                return {"error": msg, "rate_limited": True}
        try:
            return pipeline.run(cmd, allow_web=True)
        except Exception as exc:  # never 500 the public surface
            return {"error": f"research failed: {exc}"[:300], "answer": "",
                    "verdict": "Research run failed — see error.", "mode": "error"}

    @app.get("/api/demo/research/memory")
    def research_memory():
        store = pipeline.memory_store
        recent = store.all(include_demoted=False)[-10:]
        return {"stats": store.stats(),
                "recent": [{"memory_id": m.get("memory_id"), "claim": m.get("claim"),
                            "source_quality": m.get("source_quality"),
                            "source_urls": m.get("source_urls"),
                            "last_checked_at": m.get("last_checked_at"),
                            "review_status": m.get("review_status")} for m in recent]}

    if scheduler is None:
        return

    import os as _os

    def _admin_ok(request) -> bool:
        secret = _os.environ.get("RESEARCH_ADMIN_SECRET")
        if not secret:
            return True   # no secret configured (dev) — allow
        auth = (request.headers.get("authorization") or "").replace("Bearer ", "")
        return auth == secret

    @app.get("/api/demo/research/jobs")
    def research_jobs():
        return scheduler.status()

    @app.post("/api/demo/research/jobs/run")
    def research_job_run(req: JobRequest):
        if gate is not None and hasattr(gate, "check_rate"):
            ok, msg = gate.check_rate("research_job")
            if not ok:
                return {"error": msg, "rate_limited": True}
        rcpt = scheduler.run_job_now(req.job_id)
        return rcpt or {"error": f"unknown job: {req.job_id}"}

    @app.post("/api/demo/research/jobs/pause")
    def research_job_pause(req: JobRequest, request: Request):
        if not _admin_ok(request):
            return {"error": "unauthorized"}
        return {"paused": scheduler.pause(req.job_id)}

    @app.post("/api/demo/research/jobs/resume")
    def research_job_resume(req: JobRequest, request: Request):
        if not _admin_ok(request):
            return {"error": "unauthorized"}
        return {"resumed": scheduler.resume(req.job_id)}
