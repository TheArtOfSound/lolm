# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the multi-tool LOLM Operator (fake model, REAL sandbox)."""

from local_ui.agent_operator import AgentOperator, _parse_action
from local_ui.internet_tools import _resolve_ddg
from local_ui.sandbox import Sandbox


def _scripted(steps, verdict="VERIFIED: the run output proves the goal is met"):
    """A fake model: answers the strict-verifier call with `verdict`, and pulls the
    next scripted action for every normal turn (so the new self-verification step
    doesn't consume the action script)."""
    it = iter(steps)

    def fn(msgs):
        if "STRICT verifier" in (msgs[0].get("content") or ""):
            return verdict
        return next(it, "DONE: end")
    return fn


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


def test_parse_infers_write_when_header_omitted():
    # the exact live failure: model NAMES the file in STEP + fences the code but
    # forgets the `WRITE:` header → infer a write instead of wasting the step
    a = _parse_action("STEP: create primes.py with the buggy content\n```\nprint('hi')\n```")
    assert a and a["tool"] == "write" and a["path"] == "primes.py" and "print('hi')" in a["content"]
    # a fence with NO filename named anywhere → do NOT invent a file
    assert _parse_action("here is some code\n```\nprint(1)\n```") is None
    # an incidental filename INSIDE the code must not be picked up
    assert _parse_action("STEP: think\n```\nopen('data.json')\n```") is None
    # explicit tags still win over the fallback
    assert _parse_action("RUN: python3 x.py\n```\nignored\n```")["tool"] == "run"


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
    op = AgentOperator(sb, _scripted(seq), isolated=None)
    events = list(op.run("edit a file in place"))
    assert any(e["event"] == "file_changed" and e["data"].get("edit") for e in events)
    assert sb.read_file("g.py").strip() == 'print("hello LOLM")'


def test_operator_edit_rejects_missing_text(tmp_path):
    sb = Sandbox(tmp_path)
    sb.write_file("g.py", "alpha\n")
    seq = iter(["STEP: edit\nEDIT: g.py\n<<<<<<< SEARCH\nNOT THERE\n=======\nbeta\n>>>>>>> REPLACE"])
    op = AgentOperator(sb, _scripted(seq), isolated=None)
    events = list(op.run("edit"))
    assert any("didn't match" in e["data"].get("text", "") for e in events if e["event"] == "agent_note")
    assert sb.read_file("g.py") == "alpha\n"            # unchanged on a non-match


def test_operator_search_and_fetch(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter(["STEP: search\nSEARCH: latest python", "STEP: fetch\nFETCH: https://python.org"])
    op = AgentOperator(sb, _scripted(seq),
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


def test_owner_local_loopback_gate():
    """The unjailed local path must be loopback-only: a proxied/public request (x-forwarded-for,
    set by nginx) can never flip a deployed box into unjailed mode."""
    import local_ui.agent_routes as ar

    def req(host, xff=None):
        return type("R", (), {"client": type("C", (), {"host": host})(),
                              "headers": {"x-forwarded-for": xff} if xff else {}})()
    assert ar._is_loopback(req("127.0.0.1")) is True
    assert ar._is_loopback(req("::1")) is True
    assert ar._is_loopback(req("127.0.0.1", "1.2.3.4")) is False   # proxied → blocked
    assert ar._is_loopback(req("8.8.8.8")) is False


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
    op = AgentOperator(sb, _scripted(steps), isolated=None)
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
    events = list(AgentOperator(sb, _scripted(seq), isolated=None).run("compute 2+2"))
    assert any(e["event"] == "agent_note" for e in events)        # nudge fired
    assert sum(1 for e in events if e["event"] == "command_finished") == 1
    done = [e for e in events if e["event"] == "operator_done"][0]
    assert done["data"]["verified"] is True


def test_operator_context_breaks_read_stall(tmp_path):
    """Anti-stall: after re-reading a file without changing anything, the context
    must hard-steer toward an EDIT (a real failure mode a live debug run exposed —
    the model re-read the same file 7 times instead of fixing it)."""
    sb = Sandbox(tmp_path)
    op = AgentOperator(sb, lambda m: "DONE: x", isolated=None)
    op.log = [
        {"kind": "write", "summary": "wrote primes.py", "observation": "ok"},
        {"kind": "run", "summary": "ran `python3 primes.py` -> exit 0", "observation": "wrong output"},
        {"kind": "read", "summary": "read primes.py", "observation": "..."},
        {"kind": "read", "summary": "read primes.py", "observation": "..."},
        {"kind": "read", "summary": "read primes.py", "observation": "..."},
    ]
    ctx = op._context()
    assert "Reading again reveals nothing new" in ctx and "EDIT" in ctx
    # a healthy log (just wrote+ran) must NOT get the stall steer
    op.log = [{"kind": "write", "summary": "wrote a.py", "observation": "ok"},
              {"kind": "run", "summary": "ran `python3 a.py` -> exit 0", "observation": "ok"}]
    assert "Reading again reveals nothing new" not in op._context()
    # right after a SUCCESSFUL edit the context must steer to RUN (verify by executing)
    op.log = [{"kind": "edit", "changed": True, "summary": "edited a.py", "observation": "applied"}]
    assert "RUN it NOW" in op._context()
    # but a FAILED edit (no change) must NOT tell it to run an unchanged file
    op.log = [{"kind": "edit", "summary": "edit a.py — text not found", "observation": "WRITE the whole file"}]
    assert "RUN it NOW" not in op._context()


def test_operator_hard_read_cap(tmp_path):
    """A read-happy model that never acts must be FORCED to stop reading: after 3
    reads with no change, further reads are blocked outright (not just nudged)."""
    sb = Sandbox(tmp_path)
    sb.write_file("a.py", "x = 1\n")
    op = AgentOperator(sb, _scripted(["READ: a.py"] * 8), isolated=None, max_steps=8)
    events = list(op.run("inspect a.py"))
    assert any("read blocked" in e["data"].get("text", "")
               for e in events if e["event"] == "agent_note")
    # it should have actually read a few times before the block kicked in
    reads = sum(1 for e in events if e["event"] == "file_view")
    assert reads == 3


def test_operator_context_steers_to_create_missing_file(tmp_path):
    """A run that fails because a file/module was never created must steer the model
    to WRITE it (the multi-file bug: it planned two files in one WRITE, so the second
    never existed, and it kept running a missing file instead of creating it)."""
    sb = Sandbox(tmp_path)
    op = AgentOperator(sb, lambda m: "DONE: x", isolated=None)
    op.log = [{"kind": "run", "summary": "ran `python3 test_util.py` -> exit 2",
               "observation": "python3: can't open file '/work/test_util.py': [Errno 2] No such file or directory"}]
    ctx = op._context()
    assert "does NOT exist" in ctx and "test_util.py" in ctx and "WRITE" in ctx
    op.log = [{"kind": "run", "summary": "ran `python3 main.py` -> exit 1",
               "observation": "ModuleNotFoundError: No module named 'util'"}]
    ctx = op._context()
    assert "util" in ctx and "WRITE" in ctx


def test_operator_verifier_rejects_a_false_done(tmp_path):
    """Hellhound discipline: DONE is EARNED, not asserted. When the strict verifier
    rejects a finish it goes back as work; and if it never verifies, the receipt is
    HONEST (verified is False) instead of rubber-stamping "ran something"."""
    sb = Sandbox(tmp_path)
    seq = iter([
        'STEP: run\nRUN: python3 -c "raise SystemExit(1)"',     # a FAILING run
        "DONE: it totally works",
        "DONE: really it works",
        "DONE: trust me",
    ])
    op = AgentOperator(sb, _scripted(seq, verdict="NOT_VERIFIED: the run exited non-zero"),
                       isolated=None)
    events = list(op.run("make the script exit cleanly"))
    assert any(e["event"] == "verification" and e["data"]["verified"] is False for e in events)
    assert any("verifier rejected" in e["data"].get("text", "")
               for e in events if e["event"] == "agent_note")
    done = [e for e in events if e["event"] == "operator_done"][0]
    assert done["data"]["verified"] is False                    # honest, not rubber-stamped
    assert done["data"]["clean_runs"] == 0                       # nothing exited 0
