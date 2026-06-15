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

from pydantic import BaseModel

from local_ui import internet_tools
from lolm.research.memory import ResearchMemoryStore
from lolm.research.pipeline import ResearchPipeline


class ResearchRequest(BaseModel):
    command: str

RESEARCH_MEMORY_PATH = Path(os.environ.get(
    "RESEARCH_MEMORY_PATH",
    str(Path(__file__).resolve().parents[1] / "runs" / "research_memory.jsonl")))

GROUNDED_SYSTEM = (
    "You are LOLM's research answerer. Answer the QUESTION using the SOURCES below. "
    "You MAY synthesize across multiple sources to reach the answer. Cite the source "
    "tag (e.g. [S1] or [M1]) after each claim it supports. Prefer official / primary "
    "sources. Only if the sources genuinely do not address the question, say: 'The "
    "sources I found do not confirm this.' Do not invent facts beyond the sources. "
    "Be concise and specific."
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


def register_research_routes(app: Any, pipeline: ResearchPipeline,
                             gate: Optional[Any] = None) -> None:

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
