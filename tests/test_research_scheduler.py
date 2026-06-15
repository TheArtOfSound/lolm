# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the background research scheduler."""

import time

from lolm.research.memory import ResearchMemoryStore
from lolm.research.jobs import ResearchJob
from lolm.research.scheduler import ResearchScheduler


def _search(q, n):
    return {"provider": "duckduckgo", "results": [
        {"title": "Verifiable AI agent receipts - arxiv",
         "url": "https://arxiv.org/abs/2406.12345",
         "snippet": "A new competitor proposes audit trail receipts for AI agents."}]}


def _fetch(url):
    return {"text": "We present audit trail receipts for AI agents; a new competitor analysis."}


def _sched(tmp_path, **kw):
    jobs = [ResearchJob(topic="AI agent receipts", queries=["AI agent receipts"],
                        notify_on=["new competitor"]),
            ResearchJob(topic="uncertainty calibration", queries=["LLM calibration"])]
    return ResearchScheduler(jobs, search_fn=_search, fetch_fn=_fetch,
                             memory_store=ResearchMemoryStore(tmp_path / "m.jsonl"),
                             state_dir=tmp_path, first_delay=0.0, stagger=0.0, **kw)


def test_due_and_run_writes_memory_and_receipt(tmp_path):
    s = _sched(tmp_path, max_per_check=1)
    assert len(s.due(now_ts=time.time())) == 2          # both due (first_delay=0)
    ran = s.run_due()
    assert len(ran) == 1                                 # bounded to max_per_check
    assert ran[0]["memories_written"]
    assert s.memory_store.all()                          # memory persisted
    assert s.recent_receipts()                           # receipt persisted
    assert "new competitor" in (ran[0]["high_impact"])   # notify trigger matched


def test_next_run_advances_after_run(tmp_path):
    s = _sched(tmp_path)
    jid = next(iter(s.jobs))
    s.run_job_now(jid)
    # daily job → next run ~86400s out, no longer due now
    assert s._next_run[jid] > time.time() + 80_000
    assert jid not in [j.job_id for j in s.due(now_ts=time.time())]


def test_pause_excludes_from_due(tmp_path):
    s = _sched(tmp_path)
    jid = next(iter(s.jobs))
    assert s.pause(jid) is True
    assert jid not in [j.job_id for j in s.due(now_ts=time.time())]
    assert s.resume(jid) is True
    assert jid in [j.job_id for j in s.due(now_ts=time.time())]


def test_state_persists_across_reload(tmp_path):
    s = _sched(tmp_path)
    jid = next(iter(s.jobs))
    s.run_job_now(jid)
    last = s.jobs[jid].last_run_at
    # New scheduler over the same state dir reloads last_run + next_run.
    s2 = _sched(tmp_path)
    assert s2.jobs[jid].last_run_at == last
    assert jid not in [j.job_id for j in s2.due(now_ts=time.time())]


def test_status_shape(tmp_path):
    s = _sched(tmp_path)
    s.run_due()
    st = s.status()
    assert "jobs" in st and "memory_stats" in st and "memories_written_total" in st
    assert all("topic" in j and "schedule" in j for j in st["jobs"])
