# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for time-sensitivity scoring + the web-route it drives."""

from lolm.research.freshness import time_sensitivity, freshness_notice
from local_ui.research_service import web_route_events


class _FakePipe:
    def run(self, cmd, allow_web=True):
        return {"answer": "x", "verdict": "v", "sources": {"used": []}}


TIME_SENSITIVE = [
    "what is going on with iran", "who is the leader of iran", "who is the ceo of openai",
    "is there still a war in ukraine", "did the fed cut rates", "price of bitcoin",
    "what is netflix stock worth", "who won the election", "latest iphone",
    "the situation in gaza", "what's happening with the economy",
]
EVERGREEN = [
    "what is 2+2", "how does a credit score work", "why is the sky blue",
    "explain how wars start", "write a poem about rain", "a simple 3-step plan to start running",
    "what makes an AI agent trustworthy", "difference between tcp and udp",
    "how do recessions happen", "prove sqrt 2 is irrational", "just say hi",
]


def test_time_sensitive_flagged_high():
    for q in TIME_SENSITIVE:
        assert time_sensitivity(q)["risk"] == "high", q


MEDIUM = [
    "what is the tallest building in the world", "population of canada",
    "what is the capital of australia", "how old is the queen",
    "what is the most populous country", "the longest river",
]


def test_evergreen_flagged_low():
    for q in EVERGREEN:
        assert time_sensitivity(q)["risk"] == "low", q


def test_slow_changing_facts_flagged_medium():
    for q in MEDIUM:
        assert time_sensitivity(q)["risk"] == "medium", q


def test_medium_warns_but_does_not_search():
    fp = _FakePipe()
    for q in MEDIUM:
        # medium = answer from memory + honest banner, NOT a full web search
        assert web_route_events(fp, q) is None, f"medium should not search: {q}"


def test_time_sensitive_questions_route_to_web():
    fp = _FakePipe()
    for q in TIME_SENSITIVE:
        assert web_route_events(fp, q) is not None, f"should search: {q}"


def test_evergreen_questions_keep_the_nfet_theater():
    fp = _FakePipe()
    for q in EVERGREEN:
        assert web_route_events(fp, q) is None, f"should NOT search: {q}"


def test_freshness_notice_is_honest():
    n = freshness_notice("who leads iran")
    assert n["answered_from"] == "training_memory"
    assert "not a live web search" in n["message"]
    assert "latest" in n["suggestion"].lower()
