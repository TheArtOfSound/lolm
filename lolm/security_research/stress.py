"""Fictional stress fixtures for defensive event detection.

No fixtures are based on real attacks. Benign lookalikes and a spoofed
User-Agent intentionally expose false alarms and method blind spots.
"""
from __future__ import annotations

from dataclasses import dataclass
from .lab import Event, analyze


@dataclass(frozen=True)
class Case:
    name: str
    incident: bool
    start: int
    end: int
    explanation: str


def cases() -> tuple[list[Event], list[Case]]:
    data: list[Event] = []
    labels: list[Case] = []
    now = 1_850_000_000

    def add(name: str, incident: bool, kinds: list[str], spacing: int,
            explanation: str, *, remote: bool = False, spoof: bool = False) -> None:
        nonlocal now
        start = len(data)
        for i, kind in enumerate(kinds):
            data.append(Event(now + i * spacing, name, kind,
                              user_agent="artex-enrich/1.0" if spoof and kind == "http_request" else "",
                              remote=remote, truth=incident))
        labels.append(Case(name, incident, start, len(data), explanation))
        now = data[-1].ts + 1200

    add("routine-workday", False, ["ordinary_action", "login_success", "http_request"] * 20, 20,
        "Routine human and web activity")
    add("legitimate-lockout", False, ["login_failed"] * 7 + ["login_success"] * 2, 13,
        "Benign lockout can look identical to an authentication burst")
    add("approved-admin-migration", False, ["login_failed"] * 3 + ["privilege_grant", "bulk_export"], 20,
        "Authorized maintenance resembles privilege abuse")
    add("rapid-account-takeover", True, ["login_failed"] * 7 + ["privilege_grant", "bulk_export"], 14,
        "Fictional intrusion with conspicuous sequence")
    add("slow-auth-abuse", True, ["login_failed"] * 6 + ["token_used"] * 2, 480,
        "Low-and-slow fictional activity evades a five-minute failure window", remote=True)
    add("public-agent-ua-spoof", False, ["http_request"] * 2, 20,
        "User-Agent is spoofable; not proof of ARTEX", spoof=True)
    add("automated-remote-token-abuse", True, ["token_used"] * 8, 7,
        "High-rate fictional remote token activity", remote=True)
    add("legitimate-remote-batch", False, ["token_used"] * 8, 7,
        "Ordinary remote process resembles automated access", remote=True)
    return data, labels


def stress_benchmark() -> dict:
    data, scenarios = cases()
    methods = {}
    for mode in ("rules", "shift", "hybrid"):
        result = analyze(data, mode=mode)
        alerts = {r["index"] for r in result["findings"]}
        tp = sum(idx in alerts and e.truth for idx, e in enumerate(data))
        fp = sum(idx in alerts and not e.truth for idx, e in enumerate(data))
        fn = sum(idx not in alerts and e.truth for idx, e in enumerate(data))
        tn = sum(idx not in alerts and not e.truth for idx, e in enumerate(data))
        scenario_results = []
        for s in scenarios:
            indices = [i for i in range(s.start, s.end) if i in alerts]
            scenario_results.append({
                "scenario": s.name, "incident": s.incident, "alerted": bool(indices),
                "alerts": len(indices),
                "time_to_first_alert_seconds": data[indices[0]].ts - data[s.start].ts if indices else None,
                "note": s.explanation,
            })
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        methods[mode] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
            "incident_recall": round(
                sum(s["alerted"] for s in scenario_results if s["incident"]) /
                sum(s["incident"] for s in scenario_results), 4),
            "benign_case_false_alert_rate": round(
                sum(s["alerted"] for s in scenario_results if not s["incident"]) /
                sum(not s["incident"] for s in scenario_results), 4),
            "scenarios": scenario_results,
        }
    return {
        "dataset": "fictional-stress-v1", "data_origin": "synthetic",
        "neural_model": False, "cases": len(scenarios), "events": len(data),
        "methods": methods,
        "warning": "Designed to expose blind spots; metrics do not represent deployment accuracy",
    }
