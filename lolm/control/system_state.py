# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Deterministic answers to questions about the system's own state.

Trust failure #5: the model answers internal product-state questions with vague
speculation ("there may be a layer of data tracking outside awareness..."). Those
questions must be answered from METADATA, not generation. This routes a
recognised system-state question to a factual answer built from the live stats,
the run-start snapshot, and the decision packet.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from lolm.control.memory_snapshot import live_vs_snapshot

# Topic -> trigger substrings (lowercased).
_TRIGGERS = {
    "stats_diff": ["/brain/stats", "brain/stats", "memory stat", "memory count",
                   "recalls", "conversations", "turns", "stats differ", "stats route",
                   "snapshot"],
    "controller": ["controller action", "did it act", "did the controller",
                   "nfet control", "run trace", "decision packet", "did it verify",
                   "did it retrieve", "did it branch"],
    "autonomy": ["autonomy level", "autonomous", "between prompts", "tick"],
    "status": ["status route", "/health", "/uptime", "/status"],
}


def classify_system_question(question: str) -> Optional[str]:
    q = (question or "").lower()
    for topic, subs in _TRIGGERS.items():
        if any(s in q for s in subs):
            return topic
    return None


def answer_system_state_question(question: str,
                                 current_stats: Optional[Dict[str, Any]] = None,
                                 receipt_snapshot: Optional[Dict[str, Any]] = None,
                                 decision_packet: Optional[Dict[str, Any]] = None
                                 ) -> Optional[Dict[str, Any]]:
    """Return a deterministic, metadata-grounded answer, or None if not a
    system-state question (caller should then answer normally)."""
    topic = classify_system_question(question)
    if topic is None:
        return None

    if topic == "stats_diff":
        if receipt_snapshot and current_stats:
            cmp = live_vs_snapshot(receipt_snapshot, current_stats)
            text = (
                "The header is reading current live "
                f"{receipt_snapshot.get('scopeLabel', 'shared demo memory').lower()} "
                f"({cmp['live']['memories']} memories, {cmp['live']['turns']} turns) "
                "while this receipt shows a run-start snapshot "
                f"({cmp['runStart']['memories']} memories, {cmp['runStart']['turns']} turns). "
                "Both are valid; they are labelled separately. " + cmp["note"]
            )
        else:
            text = ("Two numbers exist by design: the page header shows current live "
                    "memory stats, and each receipt shows the run-start snapshot it "
                    "used. They can differ because the page is live; both are labelled.")
        return {"source": "metadata", "topic": topic, "answer": text}

    if topic == "controller":
        dp = decision_packet or {}
        action = dp.get("selectedAction", "unknown")
        triggered = dp.get("actionTriggered", False)
        if triggered:
            text = (f"On this run the controller took a real action: {action}. "
                    "The decision packet records the signals, field energy, "
                    "thresholds, and the action's outcome.")
        else:
            text = (f"On this run the controller did not take an extra action "
                    f"(selected: {action}). It measured the signals and the "
                    "event-field energy did not cross an action threshold, so it "
                    "answered/idled. Telemetry is not an action.")
        return {"source": "metadata", "topic": topic, "answer": text}

    if topic == "autonomy":
        level = (decision_packet or {}).get("autonomyLevel") or "L2_CONTROLLER_ACTIONS"
        text = (f"Current autonomy level: {level}. The system runs measured control "
                "ticks; each tick is scored, bounded, and receipt-backed. It does not "
                "claim a higher level than is implemented.")
        return {"source": "metadata", "topic": topic, "answer": text}

    if topic == "status":
        text = ("Status routes report live health/uptime; the run receipt reports "
                "the run-start snapshot. Read the status route for current state and "
                "the receipt for what a specific run saw.")
        return {"source": "metadata", "topic": topic, "answer": text}
    return None
