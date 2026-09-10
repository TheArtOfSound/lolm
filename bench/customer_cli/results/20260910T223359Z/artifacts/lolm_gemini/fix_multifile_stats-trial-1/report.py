"""Summarize a batch of latency samples."""

from stats import median, percentile


def summarize(samples):
    return {"n": len(samples), "median": median(samples)}
