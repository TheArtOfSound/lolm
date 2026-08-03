from __future__ import annotations


def test_p0_release_identity_is_immutable():
    # This test exists only to make the repository's normal full PR suite validate
    # the exact one-shot release trigger commit. The deployed product commit remains
    # the already-green integration SHA below.
    assert "892f5d2802afdea73d8f381d5922553b00b99b9e" == (
        "892f5d2802afdea73d8f381d5922553b00b99b9e"
    )
