"""Offline, defensive security-regime research for LOLM/NFET.

No execution tools, target discovery, scanning, exploitation, or network clients.
"""
from .lab import Event, analyze, benchmark, parse_jsonl, verify_receipts

__all__ = ["Event", "analyze", "benchmark", "parse_jsonl", "verify_receipts"]
