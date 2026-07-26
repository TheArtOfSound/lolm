from local_ui.memory_store import (
    MemoryStore, _tfidf_cosine, _tf, _content_tokens, _hash_embed, _hash_cosine,
)


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


def test_hash_embed_self_similarity_and_paraphrase():
    a = _hash_embed("User prefers dark mode UI theme")
    b = _hash_embed("User prefers dark mode UI theme")
    c = _hash_embed("totally unrelated quantum flux nonsense")
    assert _hash_cosine(a, b) > 0.99
    assert _hash_cosine(a, _hash_embed("prefers a dark mode theme")) > _hash_cosine(a, c)


def test_custom_embedder_plugin_slot(tmp_path):
    from local_ui.memory_store import set_embedder, embedder_kind, _embed_text
    set_embedder(lambda t: [1.0, 0.0, 0.0] if "carbonara" in (t or "").lower() else [0.0, 1.0, 0.0],
                 kind="test")
    assert embedder_kind() == "test"
    m = MemoryStore(tmp_path)
    m.append_note("The carbonara recipe uses eggs and pecorino", tag="fact", importance=4)
    m.append_note("Unrelated quantum flux", tag="fact", importance=4)
    hits = m.search_notes("how do I make carbonara pasta")
    assert hits and "carbonara" in hits[0]["text"].lower()
    # restore default
    set_embedder(None)
    assert embedder_kind() == "hash"
    assert len(_embed_text("hello world")) == 128
