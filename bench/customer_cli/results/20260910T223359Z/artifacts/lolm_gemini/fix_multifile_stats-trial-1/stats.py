"""Small statistics helpers (no third-party deps)."""


def median(values):
    vs = sorted(values)
    return vs[len(vs) // 2]


def percentile(values, p):
    vs = sorted(values)
    idx = int(len(vs) * p / 100)
    return vs[idx]
