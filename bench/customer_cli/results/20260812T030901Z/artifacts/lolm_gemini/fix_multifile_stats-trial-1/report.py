"""Summarize a batch of latency samples."""

from stats import median, percentile


def summarize(samples):
    if not samples:
        return {"n": 0, "median": None, "p90": None}
    return {
        "n": len(samples),
        "median": median(samples),
        "p90": percentile(samples, 90)
    }
