"""Small statistics helpers (no third-party deps)."""


def median(values):
    if not values:
        raise ValueError("median() arg is an empty list")
    vs = sorted(values)
    n = len(vs)
    if n % 2 == 1:
        return vs[n // 2]
    else:
        return (vs[n // 2 - 1] + vs[n // 2]) / 2


def percentile(values, p):
    if not values:
        raise ValueError("percentile() arg is an empty list")
    p = max(0, min(100, p))
    vs = sorted(values)
    idx = int((len(vs) - 1) * p / 100)
    return vs[idx]
