# Copyright (c) 2026 Qira LLC. All rights reserved.
from local_ui.continuity_tick import between_turn, model_backed_tick, _heuristic_facts
from local_ui.memory_store import MemoryStore


def test_between_turn_summarizes_and_promotes(tmp_path):
    mem = MemoryStore(tmp_path)
    out = between_turn(
        mem,
        user_text="remember my name is Casey",
        assistant_text="Got it, Casey.",
        session_id="s1",
        promote=True,
    )
    assert out["summarized"] is True
    assert "Casey" in mem.read_identity() or mem.recent_summaries(1)
    pack = out["continuity"]
    assert pack  # identity and/or recent thread


def test_between_turn_read_pack_without_new_exchange(tmp_path):
    mem = MemoryStore(tmp_path)
    mem.append_identity_line("from chat: remember my name is Casey")
    mem.add_summary("hi → hello", span="s1")
    out = between_turn(mem, user_text="", assistant_text="", session_id="s1")
    assert out["summarized"] is False
    assert "Casey" in out["continuity"] or "RECENT" in out["continuity"] or "IDENTITY" in out["continuity"]


def test_heuristic_facts_extract_name_and_prefer():
    facts = _heuristic_facts("my name is Casey and I prefer dark mode")
    joined = " ".join(facts).lower()
    assert "casey" in joined
    assert "dark" in joined or "prefer" in joined


def test_model_backed_tick_heuristic_promotes(tmp_path):
    mem = MemoryStore(tmp_path)
    out = model_backed_tick(
        mem,
        user_text="remember my name is Riley",
        assistant_text="Noted.",
        session_id="s2",
        generate=None,  # no model — heuristic only
    )
    assert out["model_used"] is False
    assert out["promoted"] >= 1 or "Riley" in mem.read_identity()
    assert any("Riley" in f or "riley" in f.lower() for f in out["facts"]) or "Riley" in mem.read_identity()
