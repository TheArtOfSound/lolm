"""Seeded, wholly synthetic incident scenarios; labels are in a separate file.

Synthetic fixtures are illustrative, not observed incidents or a LOLM evaluation.
"""
from __future__ import annotations
from dataclasses import asdict
from random import Random
from .core import Event

ATTACK_PATTERNS = {
    'credential_replay': ['auth_failure', 'auth_failure', 'auth_failure', 'token_use', 'privilege_change'],
    'app_supply_chain': ['deploy', 'unusual_app_consent', 'token_use', 'bulk_read', 'privilege_change'],
    'cloud_data_theft': ['auth_success', 'token_use', 'bulk_read', 'egress_spike'],
    'spray_then_access': ['rate_limit', 'auth_failure', 'auth_failure', 'token_use', 'privilege_change'],
    'privilege_escalation': ['auth_success', 'unusual_app_consent', 'privilege_change', 'bulk_read'],
    'stealth_login': ['auth_success', 'normal_read', 'normal_read'],
}
BENIGN_PATTERNS = {
    'password_reset': ['auth_failure', 'auth_failure', 'auth_success', 'normal_read'],
    'normal_deployment': ['deploy', 'admin_maintenance', 'normal_read', 'normal_read'],
    'quarterly_reporting': ['auth_success', 'normal_read', 'bulk_read', 'normal_read'],
    'rate_limit_recovery': ['rate_limit', 'auth_failure', 'auth_success', 'normal_read'],
    'cloud_login': ['auth_success', 'token_use', 'normal_read', 'normal_read'],
    'approved_backup': ['auth_success', 'bulk_read', 'egress_spike'],
    'authorized_app_rollout': ['deploy', 'unusual_app_consent', 'token_use', 'privilege_change'],
}

def generate(seed: int = 20261115, repeats: int = 8) -> tuple[list[dict], list[dict]]:
    if not 1 <= repeats <= 100:
        raise ValueError('repeats must be in 1..100')
    rng = Random(seed)
    events: list[dict] = []
    labels: list[dict] = []
    for group, patterns, positive in [('attack', ATTACK_PATTERNS, True),
                                      ('benign', BENIGN_PATTERNS, False)]:
        for pattern_name, sequence in patterns.items():
            for n in range(repeats):
                case = f'{group}-{pattern_name}-{n:02d}'
                person = f'synthetic-user-{case}'
                labels.append({'case_id': case, 'attack': positive, 'pattern': pattern_name})
                minute = rng.randint(10, 40)
                for i, kind in enumerate(sequence):
                    minute += rng.randint(1, 6)
                    # Secondary devices make synthetic token replay more realistic.
                    device = 'synthetic-device-b' if positive and i >= 3 else 'synthetic-device-a'
                    events.append(asdict(Event(case, f'{case}-{i}', minute, person, device, kind,
                        message='FAKE log message; text is never executed or followed')))
    rng.shuffle(events)
    rng.shuffle(labels)
    return events, labels
