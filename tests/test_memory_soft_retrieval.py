from local_ui.memory_store import MemoryStore, _tfidf_cosine, _tf, _content_tokens


def test_soft_retrieval_finds_paraphrased_personal_fact(tmp_path):
    m = MemoryStore(tmp_path)
    m.append_note("User is named Bryan and prefers dark mode", tag="fact", importance=5)
    hits = m.search_notes("what's my moniker")
    assert hits and "Bryan" in hits[0]["text"]
    hits2 = m.search_notes("prefers dark mode UI")
    assert hits2 and "dark mode" in hits2[0]["text"]


def test_tfidf_ranks_related_notes_above_noise(tmp_path):
    m = MemoryStore(tmp_path)
    m.append_note("The carbonara recipe uses eggs and pecorino", tag="fact", importance=4)
    m.append_note("Random note about quantum flux capacitors", tag="fact", importance=4)
    hits = m.search_notes("how do I make carbonara pasta")
    assert hits and "carbonara" in hits[0]["text"].lower()
    # cosine self-similarity sanity
    toks = _content_tokens("carbonara recipe eggs")
    assert _tfidf_cosine(_tf(toks), _tf(toks), {t: 1.0 for t in toks}) > 0.99
