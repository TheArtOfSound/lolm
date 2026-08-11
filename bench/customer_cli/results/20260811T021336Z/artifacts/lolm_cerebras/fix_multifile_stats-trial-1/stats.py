"""Small statistics helpers (no third-party deps)."""

import math


def median(values):
    """Return the median of a list of numbers.

    Raises:
        ValueError: If *values* is empty.
    """
    if not values:
        raise ValueError("median() arg is an empty sequence")
    vs = sorted(values)
    n = len(vs)
    mid = n // 2
    if n % 2 == 1:
        return vs[mid]
    # even length: average the two middle values
    return (vs[mid - 1] + vs[mid]) / 2.0


def percentile(values, p):
    """Return the *p*th percentile of *values*.

    *p* is clamped to the range [0, 100]. The function uses the
    nearest‑rank method and returns the element at the computed index.
    Raises ValueError if *values* is empty.
    """
    if not values:
        raise ValueError("percentile() arg is an empty sequence")
    # Clamp p to [0, 100]
    p = max(0, min(100, p))
    vs = sorted(values)
    n = len(vs)
    # Compute zero‑based index; for p=100 we want the last element
    idx = int(n * p / 100)
    # Clamp index to valid range
    idx = min(n - 1, max(0, idx))
    return vs[idx]
