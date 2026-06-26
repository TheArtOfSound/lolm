# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the multi-tool LOLM Operator (fake model, REAL sandbox)."""

from local_ui.agent_operator import AgentOperator, _parse_action
from local_ui.internet_tools import _resolve_ddg
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


def test_parse_edit_and_fetch():
    e = _parse_action("STEP: tweak\nEDIT: a.py\n<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE")
    assert e["tool"] == "edit" and e["path"] == "a.py"
    assert e["old"] == "old line" and e["new"] == "new line"
    f = _parse_action("STEP: read web\nFETCH: https://example.com/x")
    assert f["tool"] == "fetch" and f["url"] == "https://example.com/x"


def test_operator_edit_applies(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        'STEP: create\nWRITE: g.py\n```\nprint("hello world")\n```',
        'STEP: edit\nEDIT: g.py\n<<<<<<< SEARCH\nhello world\n=======\nhello LOLM\n>>>>>>> REPLACE',
    ])
    op = AgentOperator(sb, lambda m: next(seq, "DONE: end"), isolated=None)
    events = list(op.run("edit a file in place"))
    assert any(e["event"] == "file_changed" and e["data"].get("edit") for e in events)
    assert sb.read_file("g.py").strip() == 'print("hello LOLM")'


def test_operator_edit_rejects_missing_text(tmp_path):
    sb = Sandbox(tmp_path)
    sb.write_file("g.py", "alpha\n")
    seq = iter(["STEP: edit\nEDIT: g.py\n<<<<<<< SEARCH\nNOT THERE\n=======\nbeta\n>>>>>>> REPLACE"])
    op = AgentOperator(sb, lambda m: next(seq, "DONE: end"), isolated=None)
    events = list(op.run("edit"))
    assert any("not found" in e["data"].get("text", "") for e in events if e["event"] == "agent_note")
    assert sb.read_file("g.py") == "alpha\n"            # unchanged on a non-match


def test_operator_search_and_fetch(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter(["STEP: search\nSEARCH: latest python", "STEP: fetch\nFETCH: https://python.org"])
    op = AgentOperator(sb, lambda m: next(seq, "DONE: end"),
                       search_fn=lambda q: [{"title": "Python", "url": "https://python.org", "snippet": "lang"}],
                       fetch_fn=lambda u: {"url": u, "status": 200, "text": "Python is a language", "chars": 20},
                       isolated=None)
    events = list(op.run("research"))
    wr = [e for e in events if e["event"] == "web_result"][0]
    assert wr["data"]["results"][0]["url"] == "https://python.org"
    wf = [e for e in events if e["event"] == "web_fetch"][0]
    assert wf["data"]["status"] == 200


def test_ddg_redirect_decoded():
    raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdownloads%2F&rut=abc"
    assert _resolve_ddg(raw) == "https://www.python.org/downloads/"
    assert _resolve_ddg("https://direct.example.com") == "https://direct.example.com"


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
