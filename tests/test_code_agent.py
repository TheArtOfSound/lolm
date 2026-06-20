# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the agentic coding loop (fake model, REAL sandbox)."""

from local_ui.code_agent import CodeAgent, _extract_json
from local_ui.sandbox import Sandbox


def test_extract_json_tolerates_fences_and_prose():
    assert _extract_json('```json\n{"action":"run","command":"ls"}\n```')["command"] == "ls"
    assert _extract_json('Sure! {"action":"finish","summary":"done"} hope it helps')["action"] == "finish"
    assert _extract_json('{"action":"write_file","path":"a","content":"{nested:1}"}')["path"] == "a"
    assert _extract_json("no json here") is None


def test_loop_writes_runs_and_finishes(tmp_path):
    sb = Sandbox(tmp_path)
    steps = iter([
        '{"action":"write_file","path":"hello.py","content":"print(40+2)\\n"}',
        '{"action":"run","command":"python3 hello.py"}',
        '{"action":"finish","summary":"prints 42"}',
    ])
    agent = CodeAgent(sb, lambda msgs: next(steps), isolated=None)  # un-jailed for hosts w/o bwrap
    events = list(agent.run("make hello.py print 42 and run it"))
    kinds = [e["event"] for e in events]
    assert "file_changed" in kinds and "command_finished" in kinds and "code_done" in kinds
    assert sb.read_file("hello.py") == "print(40+2)\n"          # file really written
    cf = [e for e in events if e["event"] == "command_finished"][0]
    assert cf["data"]["exit_code"] == 0 and "42" in cf["data"]["stdout"]   # really ran


def test_loop_self_repairs_after_failure(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        '{"action":"write_file","path":"x.py","content":"prnt(1)\\n"}',     # typo
        '{"action":"run","command":"python3 x.py"}',                         # fails
        '{"action":"write_file","path":"x.py","content":"print(1)\\n"}',     # fixed
        '{"action":"run","command":"python3 x.py"}',                         # ok
        '{"action":"finish","summary":"fixed it"}',
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    runs = [e["data"] for e in agent.run("print 1") if e["event"] == "command_finished"]
    assert runs[0]["exit_code"] != 0          # first attempt failed
    assert runs[1]["exit_code"] == 0          # repaired attempt succeeded
    assert sb.read_file("x.py") == "print(1)\n"


def test_finish_blocked_until_code_actually_runs(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        '{"action":"write_file","path":"a.py","content":"print(1)\\n"}',
        '{"action":"finish","summary":"done (but never ran)"}',   # premature → nudged
        '{"action":"run","command":"python3 a.py"}',               # forced to run
        '{"action":"finish","summary":"actually ran it"}',         # now accepted
    ])
    events = list(CodeAgent(sb, lambda m: next(seq), isolated=None).run("print 1"))
    kinds = [e["event"] for e in events]
    assert "agent_note" in kinds                       # the premature-finish nudge fired
    assert kinds.count("command_finished") == 1        # it really ran
    done = [e for e in events if e["event"] == "code_done"][0]
    assert done["data"].get("ran") is True


def test_loop_respects_step_budget(tmp_path):
    sb = Sandbox(tmp_path)
    agent = CodeAgent(sb, lambda m: '{"action":"run","command":"echo loop"}',
                      max_steps=3, isolated=None)
    done = [e for e in agent.run("loop") if e["event"] == "code_done"][0]
    assert done["data"].get("budget_hit") is True


def test_loop_stops_on_unparseable(tmp_path):
    sb = Sandbox(tmp_path)
    agent = CodeAgent(sb, lambda m: "I will now write the code...", isolated=None)
    kinds = [e["event"] for e in agent.run("x")]
    assert "agent_note" in kinds
