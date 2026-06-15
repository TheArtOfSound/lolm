# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Autonomous research + source-backed memory — LOLM's investigation layer.

This package turns LOLM from a receipt-decorated chatbot into a real research
controller: it decides when it lacks information, searches the live web, reads
sources, writes structured source-backed memory it can reuse later, marks stale
knowledge stale, and proves through receipts exactly what changed the answer.

Modules:
  memory   — structured, source-backed, reversible memory (write/update/stale/demote)
  decide   — the search-decision layer (when to search, and why)
  pipeline — decide → search → fetch → rank → claim → memory → honest receipt
  jobs     — background research jobs that learn into memory without a prompt

Honesty is enforced, not optional: the receipt distinguishes retrieved vs opened
vs used vs ignored vs decorative vs stale, and never claims a source changed the
answer when it did not.
"""

from lolm.research.memory import (
    ResearchMemory, ResearchMemoryStore, source_quality, STALENESS,
)
from lolm.research.decide import SearchDecision, should_search

__all__ = [
    "ResearchMemory", "ResearchMemoryStore", "source_quality", "STALENESS",
    "SearchDecision", "should_search",
]
