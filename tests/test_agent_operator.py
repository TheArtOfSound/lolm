# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the multi-tool LOLM Operator (fake model, REAL sandbox)."""

from local_ui.agent_operator import AgentOperator, _parse_action
from local_ui.sandbox import Sandbox


def test_parse_each_action():
    assert _parse_action("STEP: look\nLIST")["tool"] == "list"
    assert _parse_action("READ: a.py")["path"] == "a.py"
    assert _parse_action("RUN: python3 a.py")["command"] == "python3 a.py"
    assert _parse_action("SEARCH: who is the ceo")["query"] == "who is the ceo"
    w = _parse_action('WRITE: a.py\n```\nprint(1)\n```')
    assert w["tool"] == "write" and w["path"] == "a.py" and "print(1)" in w["content"]
    assert _parse_action("DONE: shipped")["tool"] == "done"
    # a real action beats a trailing DONE in the same reply
    assert _parse_action("RUN: python3 a.py\nDONE: done")["tool"] == "run"
    assert _parse_action("no action here") is None


def test_operator_completes_a_multi_step_goal(tmp_path):
    sb = Sandbox(tmp_path)
    steps = iter([
        "STEP: see what's here\nLIST",
        'STEP: write the program\nWRITE: fib.py\n```\n'
        'def fib(n):\n    a,b=0,1\n    for _ in range(n): a,b=b,a+b\n    return a\n'
        'print([fib(i) for i in range(8)])\n```',
        "STEP: run it\nRUN: python3 fib.py",
        "DONE: fib works, prints the sequence",
    ])
    op = AgentOperator(sb, lambda m: next(steps), isolated=None)
    events = list(op.run("write and run a fibonacci program"))
    kinds = [e["event"] for e in events]
    assert "file_changed" in kinds and "command_finished" in kinds
    cf = [e for e in events if e["event"] == "command_finished"][0]
    assert cf["data"]["exit_code"] == 0 and "0, 1, 1, 2, 3, 5, 8, 13" in cf["data"]["stdout"]
    done = [e for e in events if e["event"] == "operator_done"][0]
    assert done["data"]["verified"] is True
    assert sb.read_file("fib.py").startswith("def fib")


def test_operator_blocks_premature_done(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        "DONE: I'm sure it works",                       # nothing ran → nudged
        "STEP: actually run\nRUN: python3 -c \"print(2+2)\"",
        "DONE: verified 4",
    ])
    events = list(AgentOperator(sb, lambda m: next(seq), isolated=None).run("compute 2+2"))
    assert any(e["event"] == "agent_note" for e in events)        # nudge fired
    assert sum(1 for e in events if e["event"] == "command_finished") == 1
    done = [e for e in events if e["event"] == "operator_done"][0]
    assert done["data"]["verified"] is True
