"""Semantic Version Comparison

Provides a `compare(a, b) -> int` function that follows the Semantic Versioning 2.0.0
precedence rules.

- Returns -1 if ``a`` < ``b``
- Returns  0 if ``a`` == ``b``
- Returns  1 if ``a`` > ``b``

Both inputs must be valid semantic version strings.  Invalid strings raise
`ValueError`.
"""

import re
from typing import List, Tuple, Optional

# Regular expression for a valid semver string.
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

def _parse(version: str) -> Tuple[int, int, int, Optional[List[str]]]:
    """Parse a semver string.

    Returns a tuple ``(major, minor, patch, prerelease_parts)`` where
    ``prerelease_parts`` is ``None`` when the version has no prerelease
    component, otherwise a list of identifier strings.

    Raises:
        ValueError: If the input does not conform to the semver spec.
    """
    if not isinstance(version, str):
        raise ValueError("Version must be a string")
    m = _SEMVER_RE.fullmatch(version)
    if not m:
        raise ValueError(f"Invalid semantic version: '{version}'")
    major = int(m.group('major'))
    minor = int(m.group('minor'))
    patch = int(m.group('patch'))
    prerelease = m.group('prerelease')
    prerelease_parts = prerelease.split('.') if prerelease is not None else None
    return major, minor, patch, prerelease_parts

def _compare_identifiers(id_a: str, id_b: str) -> int:
    """Compare two prerelease identifiers according to semver rules.

    Numeric identifiers are compared numerically and have lower precedence
    than alphanumeric identifiers.  Alphanumeric identifiers are compared
    lexicographically (ASCII order).
    """
    is_a_num = id_a.isdigit()
    is_b_num = id_b.isdigit()
    if is_a_num and is_b_num:
        a_int = int(id_a)
        b_int = int(id_b)
        return (a_int > b_int) - (a_int < b_int)
    if is_a_num and not is_b_num:
        # Numeric < alphanumeric
        return -1
    if not is_a_num and is_b_num:
        return 1
    # Both alphanumeric – lexical compare
    return (id_a > id_b) - (id_a < id_b)

def compare(a: str, b: str) -> int:
    """Compare two semantic version strings.

    The return value follows the convention ``-1`` if ``a`` < ``b``, ``0``
    if ``a`` == ``b`` and ``1`` if ``a`` > ``b``.

    Args:
        a: First version string.
        b: Second version string.

    Raises:
        ValueError: If either argument is not a valid semver string.
    """
    major_a, minor_a, patch_a, pre_a = _parse(a)
    major_b, minor_b, patch_b, pre_b = _parse(b)

    # Compare the core version numbers.
    if major_a != major_b:
        return (major_a > major_b) - (major_a < major_b)
    if minor_a != minor_b:
        return (minor_a > minor_b) - (minor_a < minor_b)
    if patch_a != patch_b:
        return (patch_a > patch_b) - (patch_a < patch_b)

    # At this point the core version is equal.  Handle prerelease.
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is None:
        # A version without a prerelease has higher precedence.
        return 1
    if pre_b is None:
        return -1

    # Both have prerelease components – compare dot‑separated identifiers.
    for id_a, id_b in zip(pre_a, pre_b):
        comp = _compare_identifiers(id_a, id_b)
        if comp != 0:
            return comp
    # All matched identifiers are equal; the version with fewer identifiers is lower.
    return (len(pre_a) > len(pre_b)) - (len(pre_a) < len(pre_b))

__all__ = ["compare"]
