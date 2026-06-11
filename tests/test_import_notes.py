from __future__ import annotations

from local_ui.memory_store import MemoryStore
from scripts.import_notes import guess_importance, import_folder, parse_frontmatter, split_into_chunks


def write(p, name, text):
    f = p / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return f


def test_frontmatter_and_heading_chunks(tmp_path):
    write(tmp_path / "vault", "gates.md", """---
tags: [research, lolm]
---
# Manifestation gate

The manifestation gate is defined as a per-dimension sigmoid that arbitrates
between the surface and latent streams on every feature.

It matters because removing it explodes perplexity by orders of magnitude.

# Unrelated heading

short
""")
    memory = MemoryStore(tmp_path / "data")
    stats = import_folder(tmp_path / "vault", memory)
    assert stats["files"] == 1
    assert stats["imported"] == 2          # "short" filtered by min_chars
    notes = memory.recent_notes(limit=10)
    assert all(n["tag"] == "research" for n in notes)
    assert any("Manifestation gate:" in n["text"] or "manifestation gate" in n["text"].lower()
               for n in notes)
    # definition-looking note got boosted importance
    assert any(n["importance"] == 4 for n in notes)


def test_idempotent_reimport(tmp_path):
    write(tmp_path / "vault", "a.md", "A fact about latent order models that is long enough to keep around.")
    memory = MemoryStore(tmp_path / "data")
    first = import_folder(tmp_path / "vault", memory)
    second = import_folder(tmp_path / "vault", memory)
    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["duplicates"] == 1
    assert len(memory.recent_notes(limit=10)) == 1


def test_imported_notes_are_retrievable(tmp_path):
    write(tmp_path / "vault", "recipes.md", "# Carbonara\n\nNever add cream to carbonara; the sauce is eggs and pecorino emulsified with pasta water.")
    memory = MemoryStore(tmp_path / "data")
    import_folder(tmp_path / "vault", memory)
    hits = memory.search_notes("carbonara cream", limit=5)
    assert hits and "pecorino" in hits[0]["text"]


def test_limit_and_tag_override(tmp_path):
    for i in range(5):
        write(tmp_path / "vault", f"n{i}.md", f"Note number {i} with enough characters to clear the minimum chunk size easily.")
    memory = MemoryStore(tmp_path / "data")
    stats = import_folder(tmp_path / "vault", memory, tag="forced", limit=3)
    assert stats["imported"] == 3
    assert all(n["tag"] == "forced" for n in memory.recent_notes(limit=10))


def test_helpers():
    meta, body = parse_frontmatter("---\ntags: x\n---\nbody")
    assert meta == {"tags": "x"} and body == "body"
    assert guess_importance("This is defined as the rule") == 4
    assert guess_importance("today i wrote a journal entry about lunch") == 2
    chunks = list(split_into_chunks("# H\n\npara one is long enough to pass the bar easily\n\nshort", 30, 100))
    assert len(chunks) == 1 and chunks[0].startswith("H: ")


def test_retrieval_ranks_important_relevant_notes_first(tmp_path):
    """A big imported store must surface the right note, not the newest."""
    from tests.test_nfet_agent import FakeLoop, make_agent, segment_spec

    agent, _ = make_agent(tmp_path, FakeLoop(segments=[segment_spec([3.0] * 8, "x", eos=True)]))
    mem = agent.deps.memory
    # bury one highly relevant, important note under 200 newer fillers
    mem.append_note("The manifestation gate arbitrates surface versus latent streams per dimension.",
                    tag="research", importance=5)
    for i in range(200):
        mem.append_note(f"Filler note number {i} about errands and groceries and weather patterns.",
                        tag="filler", importance=2)
    from local_ui.nfet_agent import NFETAgentRequest
    rows = agent._do_retrieve("explain the manifestation gate arbitration",
                              "", NFETAgentRequest(command="x"))
    assert rows, "expected a hit"
    assert "manifestation gate" in rows[0]["text"].lower()
