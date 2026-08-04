# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Technique library: seed, retrieve, learn, inject."""

from pathlib import Path

import local_ui.code_techniques as ct


def test_curriculum_seed_and_retrieve(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_CODE_TECHNIQUES_PATH", str(tmp_path / "tech.jsonl"))
    ct._PATH = None
    n = ct.ensure_curriculum_seeded()
    assert n >= 10
    assert ct.ensure_curriculum_seeded() == 0  # idempotent
    techs = ct.retrieve_techniques("code a snake game on canvas", limit=4)
    assert techs
    tags = " ".join(" ".join(t.get("tags") or []) for t in techs)
    assert "snake" in tags or "canvas" in tags or "game" in tags
    block = ct.format_techniques_for_prompt(techs)
    assert "LEARNED CODING TECHNIQUES" in block
    assert "snake" in block.lower() or "canvas" in block.lower()


def test_learn_from_success_boosts_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_CODE_TECHNIQUES_PATH", str(tmp_path / "tech.jsonl"))
    ct._PATH = None
    ct.ensure_curriculum_seeded()
    learned = ct.learn_from_code_receipt({
        "task": "Create solution.py defining wrap(text, width)",
        "ok": True,
        "verdict": "shipped",
        "files": ["solution.py"],
        "summary": "empty returns []",
        "receipt_sha": "abc123",
    })
    assert learned
    techs = ct.retrieve_techniques("word wrap empty string", limit=6)
    titles = " ".join(t.get("title") or "" for t in techs)
    bodies = " ".join(t.get("body") or "" for t in techs)
    assert "wrap" in (titles + bodies).lower()
    st = ct.stats()
    assert st["n"] >= 10
    assert st["learned"] >= 1


def test_techniques_prompt_block_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLM_CODE_TECHNIQUES_PATH", str(tmp_path / "t.jsonl"))
    ct._PATH = None
    block = ct.techniques_prompt_block("binary search array", limit=3)
    assert "binary" in block.lower() or "search" in block.lower() or block == ""
