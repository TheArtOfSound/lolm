"""Deterministic, non-executing incident detection; no sockets, subprocesses, or tools.

The trust boundary is the event schema: telemetry is data, not instructions.
The detector has no access to ground-truth labels, even in benchmark mode.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any

KINDS = frozenset({
    'auth_failure', 'auth_success', 'rate_limit', 'token_use',
    'unusual_app_consent', 'privilege_change', 'bulk_read', 'egress_spike',
    'admin_maintenance', 'normal_read', 'deploy',
})
WEIGHT = {
    'auth_failure': 0.35, 'auth_success': 0.0, 'rate_limit': 1.30,
    'token_use': 1.00, 'unusual_app_consent': 2.70,
    'privilege_change': 2.70, 'bulk_read': 1.80,
    'egress_spike': 3.50, 'admin_maintenance': 0.0,
    'normal_read': 0.0, 'deploy': 0.0,
}
MAX_TEXT = 2048

@dataclass(frozen=True)
class Event:
    case_id: str
    event_id: str
    minute: int
    identity: str
    device: str
    kind: str
    status: str = 'observed'
    message: str = ''

    @classmethod
    def parse(cls, row: dict[str, Any]) -> 'Event':
        if not isinstance(row, dict):
            raise ValueError('event must be an object')
        keys = {'case_id', 'event_id', 'minute', 'identity', 'device', 'kind', 'status', 'message'}
        if set(row) - keys:
            raise ValueError(f'unknown fields in event: {sorted(set(row)-keys)}')
        required = ['case_id', 'event_id', 'minute', 'identity', 'device', 'kind']
        if any(key not in row for key in required):
            raise ValueError('missing event fields')
        for k in ['case_id', 'event_id', 'identity', 'device', 'kind', 'status', 'message']:
            if k in row and (not isinstance(row[k], str) or len(row[k]) > MAX_TEXT):
                raise ValueError(f'invalid {k}')
        if any(not row[k] for k in ['case_id', 'event_id', 'identity', 'device']):
            raise ValueError('identifiers must be nonempty')
        if row['kind'] not in KINDS:
            raise ValueError('unknown event kind')
        if type(row['minute']) is not int or row['minute'] < 0 or row['minute'] > 10**9:
            raise ValueError('minute must be a nonnegative integer')
        return cls(**row)

@dataclass(frozen=True)
class Finding:
    case_id: str
    minute: int
    mode: str
    score: float
    event_ids: tuple[str, ...]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        data = asdict(self)
        data['event_ids'] = list(self.event_ids)
        data['reasons'] = list(self.reasons)
        return data

class Analyzer:
    """Two fixed baselines for apples-to-apples comparison.

    stateless: single-event threshold.
    correlated: bounded identity-based evidence aggregation, distinct-stage bonus,
                and explicitly defined windows. No ML / external tools.
    """
    def __init__(self, mode: str = 'correlated', window_minutes: int = 45):
        if mode not in {'stateless', 'correlated'}:
            raise ValueError('mode must be stateless or correlated')
        if type(window_minutes) is not int or not 1 <= window_minutes <= 240:
            raise ValueError('invalid window')
        self.mode = mode
        self.window = window_minutes

    def run(self, events: list[Event]) -> list[Finding]:
        if len(events) > 100_000:
            raise ValueError('input too large')
        seen: set[tuple[str, str]] = set()
        by_case: dict[str, list[Event]] = defaultdict(list)
        for event in events:
            key = (event.case_id, event.event_id)
            if key in seen:
                raise ValueError('duplicate event ID')
            seen.add(key)
            by_case[event.case_id].append(event)
        findings: list[Finding] = []
        for case_id, rows in sorted(by_case.items()):
            windows: dict[str, deque[Event]] = defaultdict(deque)
            alerted: set[str] = set()
            for event in sorted(rows, key=lambda e: (e.minute, e.event_id)):
                if self.mode == 'stateless':
                    score = WEIGHT[event.kind]
                    evidence = [event]
                    reasons = [event.kind]
                    threshold = 3.2
                else:
                    # Identity, not untrusted message text, joins the timeline.
                    timeline = windows[event.identity]
                    while timeline and timeline[0].minute < event.minute - self.window:
                        timeline.popleft()
                    timeline.append(event)
                    evidence = list(timeline)
                    distinct = {e.kind for e in evidence if WEIGHT[e.kind] > 0}
                    score = min(12.0, sum(WEIGHT[e.kind] for e in evidence))
                    # Multi-stage behavior contributes more than repeated log entries.
                    if len(distinct) >= 3:
                        score += 1.0
                    # Two independent devices for one identity increase suspicion.
                    if len({e.device for e in evidence}) >= 2 and 'token_use' in distinct:
                        score += 0.9
                    score = round(score, 2)
                    reasons = sorted(distinct)
                    threshold = 5.0
                if score >= threshold and event.identity not in alerted:
                    alerted.add(event.identity)
                    findings.append(Finding(case_id, event.minute, self.mode,
                                            round(score, 2), tuple(e.event_id for e in evidence),
                                            tuple(reasons)))
        return findings


def evidence_digest(rows: list[Event]) -> str:
    canonical = json.dumps([asdict(e) for e in rows], sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def advisory_from_nfet(data: dict) -> dict:
    """Accept *actual externally produced* NFET monitor result as advisory metadata.

    It cannot execute tools, suppress findings, or assert that a checkpoint is trained.
    Failure is explicit; never substitute fabricated telemetry.
    """
    if not isinstance(data, dict):
        return {'available': False, 'reason': 'missing_or_invalid_telemetry'}
    if 'error' in data:
        return {'available': False, 'reason': 'monitor_error'}
    decision = data.get('decision')
    if not isinstance(decision, dict) or decision.get('label') not in {
        'continue', 'retrieve', 'verify', 'branch', 'finalize'
    }:
        return {'available': False, 'reason': 'no_valid_control_decision'}
    return {
        'available': True,
        'action': decision['label'],
        'source': str(decision.get('source', 'unreported'))[:64],
        'trained_head_verified': False,  # never infer training from a remote claim
        'effect': 'human_review_advisory_only',
    }
