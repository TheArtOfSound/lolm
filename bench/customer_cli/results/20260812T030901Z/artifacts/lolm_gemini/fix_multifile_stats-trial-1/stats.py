"""Small statistics helpers (no third-party deps)."""


def median(values):
    if not values:
        raise ValueError("median() arg is an empty list")
    vs = sorted(values)
    n = len(vs)
    if n % 2 == 1:
        return float(vs[n // 2])
    else:
        return (vs[n // 2 - 1] + vs[n // 2]) / 2.0


def percentile(values, p):
    if not values:
        raise ValueError("percentile() arg is an empty list")
    p = max(0, min(100, p))
    vs = sorted(values)
    # Using nearest rank method
    idx = int(len(vs) * p / 100)
    if idx >= len(vs):
        idx = len(vs) - 1
    return vs[idx]
