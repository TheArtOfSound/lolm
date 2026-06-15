# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for background research jobs (learn into memory without a prompt)."""

from lolm.research.memory import ResearchMemoryStore
from lolm.research.jobs import ResearchJob, run_job, default_jobs


def _search(q, n):
    return {"provider": "duckduckgo", "results": [
        {"title": "Verifiable AI agent logs - paper",
         "url": "https://arxiv.org/abs/2406.00001",
         "snippet": "We present an audit trail receipt for AI agents."},
        {"title": "Random forum thread", "url": "https://reddit.com/r/ai/x",
         "snippet": "some unrelated chatter about cats"}]}


def _fetch(url):
    if "arxiv" in url:
        return {"text": "We present an audit trail receipt system for AI agents with "
                        "verifiable run logs and a new competitor analysis."}
    return {"text": "cats are nice and fluffy and unrelated"}


def test_default_jobs_cover_watch_topics():
    jobs = default_jobs()
    topics = " ".join(j.topic.lower() for j in jobs)
    assert "receipt" in topics and "calibration" in topics and "competitor" in topics
    assert all(j.job_id.startswith("research_") for j in jobs)


def test_run_job_writes_source_backed_memory(tmp_path):
    store = ResearchMemoryStore(tmp_path / "m.jsonl")
    job = ResearchJob(topic="AI agent receipts and verifiable run logs",
                      queries=["verifiable AI agent logs"], notify_on=["new competitor"])
    rcpt = run_job(job, search_fn=_search, fetch_fn=_fetch, memory_store=store)
    assert rcpt["sources_checked"] == 2
    assert rcpt["memories_written"]                    # the high-quality arxiv source
    # the low-quality reddit source must NOT have produced a memory
    mems = store.all()
    assert all("arxiv" in (m.get("source_urls") or [""])[0] for m in mems)
    assert "new competitor" in rcpt["high_impact"]     # 'competitor' appeared in source
    assert rcpt["status"] in ("ok", "partial")


def test_human_review_flag_on_memory(tmp_path):
    store = ResearchMemoryStore(tmp_path / "m.jsonl")
    job = ResearchJob(topic="t", queries=["q"], human_review_required=True)
    run_job(job, search_fn=_search, fetch_fn=_fetch, memory_store=store)
    assert all(m["review_status"] == "needs_human_review" for m in store.all())
