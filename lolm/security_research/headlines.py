"""Offline, source-aware cyber headline provenance and deduplication.

This is NOT a crawler or proof of a globally first-reported attack. The corpus is
only the claims that a researcher loaded. Never infer cyberattacks from outages.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, Iterable
import json

SOURCES = frozenset({"official", "vendor", "researcher", "news", "actor_claim"})
STATUSES = frozenset({"confirmed", "reported", "claimed", "disputed", "refuted"})
CATEGORIES = frozenset({"incident", "advisory", "analysis", "detection_release"})
AI_ROLES = frozenset({"verified", "suspected", "not_established"})


def timestamp(s: str) -> datetime:
    if not isinstance(s, str) or len(s) > 40:
        raise ValueError("timestamp must be a bounded ISO-8601 string")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamps must have a timezone offset")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Claim:
    incident_id: str
    title: str
    published_at: str
    source_url: str
    source_class: str
    status: str
    category: str
    occurred_at: str | None = None
    ai_role: str = "not_established"

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Claim":
        if not isinstance(raw, dict):
            raise ValueError("claim must be an object")
        c = cls(**raw)
        if not isinstance(c.incident_id, str) or not 2 <= len(c.incident_id) <= 128:
            raise ValueError("incident_id invalid")
        if not isinstance(c.title, str) or not 4 <= len(c.title) <= 300:
            raise ValueError("title invalid")
        parsed = urlparse(c.source_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("source_url must be a public HTTPS URL without credentials")
        timestamp(c.published_at)
        if c.occurred_at is not None:
            timestamp(c.occurred_at)
        if c.source_class not in SOURCES or c.status not in STATUSES or c.category not in CATEGORIES:
            raise ValueError("unsupported source/status/category")
        if c.ai_role not in AI_ROLES:
            raise ValueError("unsupported ai attribution")
        return c


def parse_claims(lines: Iterable[str]) -> list[Claim]:
    claims: list[Claim] = []
    for i, line in enumerate(lines, 1):
        if i > 10_000:
            raise ValueError("claim count limit reached")
        if len(line.encode("utf-8")) > 8_192:
            raise ValueError("claim line size limit reached")
        if line.strip():
            try:
                claims.append(Claim.parse(json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"claim {i} invalid: {exc}") from exc
    return claims


def headline_audit(claims: list[Claim], cutoff: str) -> dict[str, Any]:
    """Answer 'first captured in this corpus' not 'first known globally'."""
    pivot = timestamp(cutoff)
    grouped: dict[str, list[Claim]] = {}
    for claim in claims:
        grouped.setdefault(claim.incident_id.casefold(), []).append(claim)
    entries = []
    for incident_id, group in sorted(grouped.items()):
        first = min(group, key=lambda c: timestamp(c.published_at))
        published = timestamp(first.published_at)
        verified_claims = [c for c in group if c.status == "confirmed" and c.source_class in {"official", "vendor"}]
        confirmed_incident = bool(verified_claims) and any(c.category == "incident" for c in verified_claims)
        contradicted = any(c.status == "refuted" for c in group) and any(c.status == "confirmed" for c in group)
        new_in_corpus = published > pivot
        entries.append({
            "incident_id": incident_id,
            "first_captured_publication": published.isoformat(),
            "event_occurrences": sorted({timestamp(c.occurred_at).isoformat() for c in group if c.occurred_at}),
            "claims": len(group),
            "source_urls": sorted({c.source_url for c in group}),
            "confirmed_incident_in_corpus": confirmed_incident,
            "new_report_in_corpus_since_cutoff": new_in_corpus,
            "new_confirmed_incident_in_corpus": bool(new_in_corpus and confirmed_incident and not contradicted),
            "contradictory_claims": contradicted,
            "ai_involvement_supported": any(c.ai_role == "verified" and c in verified_claims for c in group),
        })
    return {
        "method": "corpus-local deduplication, not global web coverage",
        "cutoff": pivot.isoformat(), "submitted_claims": len(claims),
        "distinct_items": len(entries),
        "new_confirmed_incidents_in_corpus": sum(e["new_confirmed_incident_in_corpus"] for e in entries),
        "items": entries,
    }
