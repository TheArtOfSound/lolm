from local_ui.memory_store import MemoryStore


def test_soft_retrieval_finds_paraphrased_personal_fact(tmp_path):
    m = MemoryStore(tmp_path)
    m.append_note("User is named Bryan and prefers dark mode", tag="fact", importance=5)
    hits = m.search_notes("what's my moniker")
    assert hits and "Bryan" in hits[0]["text"]
    hits2 = m.search_notes("prefers dark mode UI")
    assert hits2 and "dark mode" in hits2[0]["text"]
