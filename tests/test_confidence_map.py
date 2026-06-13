from lolm.confidence_map import _is_contentful, confidence_spans


def test_contentful_filter():
    assert not _is_contentful("and")
    assert not _is_contentful("a")
    assert not _is_contentful("of the")
    assert _is_contentful("manifestation gate")
    assert _is_contentful("are named")
    assert _is_contentful("zorbance coefficient")


def test_confidence_spans_degrades_without_graft():
    r = confidence_spans(None, None, "some text")
    assert r["available"] is False and r["spans"] == []
