"""Small statistics helpers (no third-party deps)."""


def median(values):
    if not values:
        raise ValueError("median() arg is an empty sequence")
    vs = sorted(values)
    n = len(vs)
    mid = n // 2
    if n % 2 == 1:
        return vs[mid]
    else:
        return (vs[mid - 1] + vs[mid]) / 2


def percentile(values, p):
    if not values:
        raise ValueError("percentile() arg is an empty sequence")
    p = max(0, min(100, p))
    vs = sorted(values)
    # Using nearest-rank method: index = ceil(p/100 * n) - 1
    # or more common in programming:
    # index = int(p/100 * (len(vs) - 1))
    import math
    idx = math.ceil(p / 100 * len(vs)) - 1
    idx = max(0, min(len(vs) - 1, idx))
    return vs[idx]
