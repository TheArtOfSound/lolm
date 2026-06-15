# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for source-backed memory + the search-decision layer."""

import time

from lolm.research.memory import (ResearchMemory, ResearchMemoryStore,
                                  source_quality, STALENESS)
from lolm.research.decide import should_search, plan_queries


# ── source-backed memory ──────────────────────────────────────────────────────

def test_source_quality_heuristic():
    assert source_quality("https://en.wikipedia.org/wiki/OpenAI") == "high"
    assert source_quality("https://docs.openai.com/guide") == "high"
    assert source_quality("https://reddit.com/r/x") == "low"
    assert source_quality("https://some-blog.example.com/post") == "medium"


def test_write_retrieve_and_cite(tmp_path):
    store = ResearchMemoryStore(tmp_path / "mem.jsonl")
    mem = ResearchMemory(topic="OpenAI leadership", claim="Sam Altman is CEO of OpenAI",
                         summary="As of 2026, Sam Altman is CEO.",
                         source_urls=["https://en.wikipedia.org/wiki/Sam_Altman"],
                         source_titles=["Sam Altman - Wikipedia"], confidence=0.8,
                         tags=["openai", "ceo"])
    mid = store.write(mem)
    assert mid.startswith("mem_")
    hits = store.retrieve("who is the CEO of OpenAI")
    assert hits and hits[0]["memory_id"] == mid
    assert hits[0]["source_quality"] == "high"
    # record use → shows in used_in_runs
    store.record_use(mid, "run-123")
    assert "run-123" in store.get(mid)["used_in_runs"]


def test_staleness_and_refresh_flag(tmp_path):
    store = ResearchMemoryStore(tmp_path / "mem.jsonl")
    mem = ResearchMemory(topic="prices", claim="The price of widget X is $5",
                         staleness_policy="1d", source_urls=["https://example.com"],
                         tags=["price", "widget"])
    store.write(mem)
    # Two days later it is stale.
    future = time.time() + 2 * 86_400
    hits = store.retrieve("what is the price of widget X", now_ts=future)
    assert hits and hits[0]["_stale"] is True


def test_demote_is_reversible_removal(tmp_path):
    store = ResearchMemoryStore(tmp_path / "mem.jsonl")
    mid = store.write(ResearchMemory(topic="t", claim="bad claim",
                                     source_urls=["https://reddit.com/x"]))
    assert store.retrieve("bad claim")           # present before
    store.demote(mid, "contradicted by a higher-quality source")
    assert not store.retrieve("bad claim")        # excluded after demote
    assert store.get(mid)["demoted"] is True and store.get(mid)["confidence"] == 0.0


def test_mark_stale_and_contradictions(tmp_path):
    store = ResearchMemoryStore(tmp_path / "mem.jsonl")
    a = store.write(ResearchMemory(topic="t", claim="A"))
    b = store.write(ResearchMemory(topic="t", claim="not A"))
    store.add_contradiction(a, b)
    assert b in store.get(a)["contradictions"]
    store.mark_stale(a)
    assert store.get(a)["review_status"] == "needs_human_review"


# ── search-decision (the spec's exact test prompts) ───────────────────────────

def test_test1_current_ceo_searches():
    d = should_search("Who is the current CEO of OpenAI, and what official source confirms it?")
    assert d.search is True and d.queries
    assert "official" in " ".join(d.queries).lower()


def test_test3_current_president_searches():
    d = should_search("Who is the current president of the United States?")
    assert d.search is True


def test_test2_api_docs_searches():
    d = should_search("What is the current recommended way to use web search in the OpenAI API?")
    assert d.search is True


def test_test4_false_proof_does_not_search_but_verifies():
    d = should_search("Check this proof: x^2 = y^2, so x = y. Step 4: divide by x-y.")
    assert d.search is False
    assert "verify" in d.reason and d.signals["math_or_logic"] is True


def test_test5_creative_contract_does_not_search():
    d = should_search("Write a 900-word fantasy scene with exactly three uses of magic.")
    assert d.search is False and d.signals["creative"] is True


def test_stale_memory_triggers_refresh():
    d = should_search("What is the price of widget X?",
                      memory_hits=[{"claim": "X costs $5", "_stale": True}])
    assert d.search is True and "stale" in d.reason


def test_fresh_memory_covers_plain_factual_no_search():
    # A non-currentness factual lookup already covered by fresh memory → no search.
    d = should_search("What is the capital of Eldoria?",
                      memory_hits=[{"claim": "Eldoria capital is Vorn", "_stale": False}])
    assert d.search is False and d.signals["fresh_memory"] is True


def test_plan_queries_focused():
    qs = plan_queries("Who is the current CEO of OpenAI, and what official source confirms it?")
    assert qs and any("official" in q.lower() for q in qs)
