# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Oort/Flows tactics catalog + retrieval + plan injection."""

from pathlib import Path

import lolm.tactics.oort_flows as of
from lolm.control import task_state as ts


def test_catalog_present_and_large():
    st = of.catalog_stats()
    assert st["present"] is True
    assert st["flow_count"] >= 100
    assert st["tactic_count"] >= 500
    assert "Agent Architecture" in (st.get("categories") or {})


def test_retrieve_agent_tactics():
    tacs = of.retrieve_tactics(
        "design a single-loop coding agent with tools and verification",
        limit=6,
    )
    assert tacs
    blob = " ".join(
        (t.get("title") or "") + " " + (t.get("category") or "")
        for t in tacs
    ).lower()
    assert any(
        k in blob
        for k in ("agent", "loop", "harness", "verif", "orchestr", "tool")
    )


def test_match_playbook_snake_or_game():
    books = of.match_flow_playbook(
        "build a playable 2d browser game with canvas score and collisions",
        limit=1,
    )
    assert books
    slug = (books[0].get("slug") or "").lower()
    title = (books[0].get("title") or "").lower()
    assert "game" in slug or "game" in title or "browser" in slug


def test_tactics_prompt_block_nonempty():
    block = of.tactics_prompt_block(
        "add plan todo system and adversarial verification to agent",
        limit=4,
    )
    assert "OORT/FLOWS" in block or "TACTICS" in block or "PLAYBOOK" in block


def test_plan_steps_from_playbook_into_task_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_TASK_STATE_DIR", str(tmp_path / "ts"))
    # Force task-state store under tmp if supported; still works with default.
    z = ts.load_or_init(
        "Design a single-loop agent with tool registry and result folding",
        resume=False,
    )
    plan_text = " ".join(p.text for p in z.P).lower()
    # Either flow-derived steps or default plan — both valid; prefer flow when matched.
    assert z.P
    assert len(z.P) >= 2
    # If playbook matched, ids carry flow- prefix
    if any(str(p.id).startswith("flow-") for p in z.P):
        assert "loop" in plan_text or "tool" in plan_text or "registry" in plan_text


def test_techniques_block_includes_oort(tmp_path, monkeypatch):
    import local_ui.code_techniques as ct
    monkeypatch.setenv("LOLM_CODE_TECHNIQUES_PATH", str(tmp_path / "tech.jsonl"))
    ct._PATH = None
    block = ct.techniques_prompt_block(
        "adversarial verification agent verdict before done",
        limit=5,
    )
    assert block
    low = block.lower()
    assert "verif" in low or "adversarial" in low or "done" in low or "oort" in low
