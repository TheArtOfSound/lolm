"""Summarize a batch of latency samples."""

from stats import median, percentile


def summarize(samples):
    """Return a summary dict for *samples*.

    The returned dict contains:
        - "n": number of samples
        - "median": median value
        - "p90": 90th percentile
    """
    return {
        "n": len(samples),
        "median": median(samples),
        "p90": percentile(samples, 90),
    }
