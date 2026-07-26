# Copyright (c) 2026 Qira LLC. All rights reserved.
from local_ui.continuity_tick import between_turn
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
