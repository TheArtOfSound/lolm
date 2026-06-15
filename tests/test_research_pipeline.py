# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the research pipeline — honest retrieved/opened/used/decorative."""

from lolm.research.memory import ResearchMemory, ResearchMemoryStore
from lolm.research.pipeline import ResearchPipeline, unwrap_url


def _ceo_search(q, n):
    return {"provider": "duckduckgo", "results": [
        {"title": "Sam Altman - Wikipedia",
         "url": "https://en.wikipedia.org/wiki/Sam_Altman",
         "snippet": "Sam Altman is the chief executive officer of OpenAI."}]}


def _ceo_fetch(url):
    return {"title": "Sam Altman - Wikipedia",
            "text": "Sam Altman is the chief executive officer of OpenAI since 2019."}


def test_unwrap_ddg_redirect():
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FOpenAI&rut=x"
    assert unwrap_url(wrapped) == "https://en.wikipedia.org/wiki/OpenAI"
    assert unwrap_url("https://docs.openai.com") == "https://docs.openai.com"


def test_searches_uses_source_and_writes_memory(tmp_path):
    store = ResearchMemoryStore(tmp_path / "m.jsonl")
    pipe = ResearchPipeline(
        memory_store=store, search_fn=_ceo_search, fetch_fn=_ceo_fetch,
        answer_fn=lambda p, s, m: "Sam Altman is the current CEO of OpenAI, per Wikipedia.")
    out = pipe.run("Who is the current CEO of OpenAI, and what official source confirms it?")
    assert out["mode"] == "live_web_research"
    assert out["search_decision"]["search"] is True
    assert len(out["sources"]["opened"]) == 1
    assert len(out["sources"]["used"]) == 1          # the source materially shaped it
    assert out["memories"]["written"]                # learned a source-backed memory
    assert "materially shaped" in out["verdict"]
    # the action log is in order and includes the real steps
    kinds = [a["action"] for a in out["actions"]]
    assert "search_web" in kinds and "open_source" in kinds and "write_memory" in kinds


def test_decorative_retrieval_is_labeled_honestly(tmp_path):
    store = ResearchMemoryStore(tmp_path / "m.jsonl")
    pipe = ResearchPipeline(
        memory_store=store, search_fn=_ceo_search, fetch_fn=_ceo_fetch,
        # the answer ignores the source entirely
        answer_fn=lambda p, s, m: "I cannot reliably determine that right now.")
    out = pipe.run("Who is the current CEO of OpenAI?")
    assert out["sources"]["opened"] and not out["sources"]["used"]
    assert "0 materially changed" in out["verdict"]
    assert out["answer_improved_by_research"] is False
    assert not out["memories"]["written"]            # nothing used → nothing learned


def test_logic_prompt_does_not_search(tmp_path):
    store = ResearchMemoryStore(tmp_path / "m.jsonl")
    called = []
    pipe = ResearchPipeline(
        memory_store=store, search_fn=lambda q, n: called.append(q) or {"results": []},
        answer_fn=lambda p, s, m: "Step 4 is invalid: division by x-y fails when x=y. "
                                  "Counterexample x=1, y=-1.")
    out = pipe.run("Check this proof: x^2 = y^2, so x = y. Step 4: divide by x-y.")
    assert out["search_decision"]["search"] is False
    assert called == []                              # never searched
    assert out["mode"] == "model_only"
    assert "model knowledge" in out["verdict"]


def test_fresh_memory_grounds_without_search(tmp_path):
    store = ResearchMemoryStore(tmp_path / "m.jsonl")
    store.write(ResearchMemory(topic="Eldoria", claim="The capital of Eldoria is Vorn",
                               summary="Eldoria's capital city is Vorn.",
                               source_urls=["https://en.wikipedia.org/wiki/Eldoria"],
                               staleness_policy="never", tags=["eldoria", "capital"]))
    called = []
    pipe = ResearchPipeline(
        memory_store=store, search_fn=lambda q, n: called.append(q) or {"results": []},
        answer_fn=lambda p, s, m: "The capital of Eldoria is Vorn.")
    out = pipe.run("What is the capital of Eldoria?")
    assert out["search_decision"]["search"] is False  # fresh memory covers it
    assert called == []
    assert out["memories"]["used"] and "memory" in out["verdict"]
