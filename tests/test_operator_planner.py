# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the frontier-backed planner (fake chat_fn, no model)."""

from local_ui.operator_planner import FrontierPlanner, extract_plan


def test_extract_plan_plain_json():
    p = extract_plan('{"action":"tool","tool":"run_python","args":{"code":"x"}}')
    assert p["action"] == "tool" and p["tool"] == "run_python"


def test_extract_plan_strips_fences_and_prose():
    text = 'Sure!\n```json\n{"action":"finish","answer":"42"}\n```\nHope that helps.'
    p = extract_plan(text)
    assert p == {"action": "finish", "answer": "42"}


def test_extract_plan_trailing_prose_after_object():
    p = extract_plan('{"action":"finish","answer":"ok"} and then more text')
    assert p["action"] == "finish" and p["answer"] == "ok"


def test_extract_plan_garbage_is_empty():
    assert extract_plan("no json here at all") == {}
    assert extract_plan("") == {}


def test_planner_returns_valid_tool_plan():
    planner = FrontierPlanner(lambda msgs: '{"action":"tool","tool":"web_read",'
                              '"args":{"url":"https://example.com"},"reason":"r"}')
    plan = planner("look up X", [])
    assert plan["tool"] == "web_read" and plan["action"] == "tool"


def test_planner_degrades_to_finish_on_non_json():
    # A model that ignores the format must NEVER yield a guessed tool action.
    planner = FrontierPlanner(lambda msgs: "I think the answer is 42.")
    plan = planner("q", [])
    assert plan["action"] == "finish" and "42" in plan["answer"]


def test_planner_handles_chat_exception():
    def boom(msgs):
        raise RuntimeError("provider down")
    plan = FrontierPlanner(boom)("q", [])
    assert plan["action"] == "finish" and "planner error" in plan["answer"]


def test_planner_feeds_history_into_prompt():
    seen = {}
    def capture(msgs):
        seen["user"] = msgs[-1]["content"]
        return '{"action":"finish","answer":"done"}'
    FrontierPlanner(capture)("goal", [
        {"tool": "web_read", "args": {"url": "u"}, "decision": "act",
         "outcome": "verified", "observation": "HTTP 200"},
    ])
    assert "web_read" in seen["user"] and "verified" in seen["user"]
