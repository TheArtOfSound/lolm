"""Small statistics helpers (no third-party deps)."""


def median(values):
    if not values:
        raise ValueError("median() requires a non-empty list")
    vs = sorted(values)
    n = len(vs)
    mid = n // 2
    if n % 2 == 0:
        return (vs[mid - 1] + vs[mid]) / 2
    return float(vs[mid])


def percentile(values, p):
    if not values:
        raise ValueError("percentile() requires a non-empty list")
    p = max(0, min(100, p))
    vs = sorted(values)
    n = len(vs)
    # Using the nearest rank method or interpolation?
    # Simple index:
    idx = int((n - 1) * p / 100)
    return vs[idx]
