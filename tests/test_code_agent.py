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
    # skip py_compile verify events — look at the real program run
    cf = [e for e in events if e["event"] == "command_finished" and not e["data"].get("verify")][0]
    assert cf["data"]["exit_code"] == 0 and "42" in cf["data"]["stdout"]   # really ran


def test_loop_self_repairs_after_failure(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        '{"action":"write_file","path":"x.py","content":"prnt(1)\\n"}',     # typo
        '{"action":"run","command":"python3 x.py"}',                         # fails (or auto-run already did)
        '{"action":"write_file","path":"x.py","content":"print(1)\\n"}',     # fixed
        '{"action":"run","command":"python3 x.py"}',                         # ok
        '{"action":"finish","summary":"fixed it"}',
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    runs = [e["data"] for e in agent.run("print 1") if e["event"] == "command_finished"
            and not e["data"].get("verify")]
    assert runs, "expected at least one command"
    assert any(r["exit_code"] != 0 for r in runs)     # saw the broken attempt
    assert any(r["exit_code"] == 0 for r in runs)     # repaired attempt succeeded
    # last green run must come after a failure (repair order)
    first_fail = next(i for i, r in enumerate(runs) if r["exit_code"] != 0)
    first_ok = next(i for i, r in enumerate(runs) if r["exit_code"] == 0)
    assert first_ok > first_fail
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
    real_runs = [e for e in events if e["event"] == "command_finished" and not e["data"].get("verify")]
    assert len(real_runs) >= 1                         # it really ran the program
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


def test_json_multi_action_write_and_run(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        '{"actions":[{"action":"write_file","path":"m.py","content":"print(7*6)\\n"},'
        '{"action":"run","command":"python3 m.py"}]}',
        '{"action":"finish","summary":"42"}',
    ])
    events = list(CodeAgent(sb, lambda m: next(seq), isolated=None).run("print 42"))
    kinds = [e["event"] for e in events]
    assert "file_changed" in kinds and "command_finished" in kinds and "code_done" in kinds
    cf = [e for e in events if e["event"] == "command_finished" and not e["data"].get("verify")][0]
    assert cf["data"]["exit_code"] == 0 and "42" in cf["data"]["stdout"]


def test_py_compile_blocks_run_on_syntax_error(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        # broken syntax — compile should fail, no successful program run
        '{"action":"write_and_run","path":"bad.py","content":"def f(\\n","command":"python3 bad.py"}',
        '{"action":"write_and_run","path":"bad.py","content":"print(1)\\n","command":"python3 bad.py"}',
        '{"action":"finish","summary":"fixed"}',
    ])
    events = list(CodeAgent(sb, lambda m: next(seq), isolated=None).run("print 1"))
    notes = " ".join(e["data"].get("text", "") for e in events if e["event"] == "agent_note")
    assert "py_compile" in notes or "SYNTAX" in notes or "syntax" in notes.lower()
    # eventually should succeed
    assert any(e["event"] == "code_done" for e in events)


def test_auto_done_when_expected_output_prints(tmp_path):
    """Oracle green → finish without waiting for model DONE (speed-to-value)."""
    sb = Sandbox(tmp_path)
    calls = {"n": 0}

    def chat(msgs):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"action":"write_and_run","path":"h.py","content":"print(42)\\n","command":"python3 h.py"}'
        raise AssertionError("model should not be called again after auto-DONE")

    events = list(CodeAgent(sb, chat, isolated=None).run("make h.py print 42 and run it"))
    assert any(e["event"] == "code_done" for e in events)
    notes = " ".join(e["data"].get("text", "") for e in events if e["event"] == "agent_note")
    assert "oracle green" in notes or "auto-verified" in notes
    receipt = [e["data"] for e in events if e["event"] == "code_receipt"][-1]
    assert receipt.get("ok") is True
    assert calls["n"] == 1


def test_edit_tool_surgical_fix(tmp_path):
    sb = Sandbox(tmp_path)
    sb.write_file("z.py", "prnt(3)\n")
    seq = iter([
        '{"action":"edit_file","path":"z.py","old":"prnt(3)","new":"print(3)"}',
        # auto-run may fire after edit; if not, explicit run
        '{"action":"run","command":"python3 z.py"}',
        '{"action":"finish","summary":"fixed"}',
    ])
    events = list(CodeAgent(sb, lambda m: next(seq), isolated=None).run("fix print"))
    assert "print(3)" in sb.read_file("z.py")
    assert any(e["event"] == "command_finished" and e["data"].get("exit_code") == 0
               for e in events)


def test_syntaxerror_coaches_surgical_fix(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        '{"action":"write_and_run","path":"buggy.py","content":"def f(\\n  return 1\\n","command":"python3 buggy.py"}',
        '{"action":"write_and_run","path":"buggy.py","content":"def f():\\n  return 1\\nprint(f())\\n","command":"python3 buggy.py"}',
        '{"action":"finish","summary":"fixed syntax"}',
    ])
    events = list(CodeAgent(sb, lambda m: next(seq), isolated=None).run("fix syntax and print 1"))
    notes = " ".join(e["data"].get("text", "") for e in events if e["event"] == "agent_note")
    assert ("SyntaxError" in notes or "surgical fix" in notes or "line" in notes
            or "py_compile" in notes or "SYNTAX" in notes)
    assert any(e["event"] == "code_receipt" and e["data"].get("ok") for e in events)


def test_modulenotfound_coaches_missing_file(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        '{"action":"write_and_run","path":"main.py","content":"import helper\\nprint(helper.x)\\n",'
        '"command":"python3 main.py"}',
        '{"action":"write_and_run","path":"helper.py","content":"x=9\\n","command":"python3 main.py"}',
        '{"action":"finish","summary":"works"}',
    ])
    events = list(CodeAgent(sb, lambda m: next(seq), isolated=None).run("print helper value"))
    notes = " ".join(e["data"].get("text", "") for e in events if e["event"] == "agent_note")
    assert "helper.py" in notes or "import failed" in notes
    assert any(e["event"] == "code_receipt" for e in events)
    assert "x=9" in sb.read_file("helper.py")


def test_code_receipt_emitted_and_blocks_wrong_output(tmp_path):
    sb = Sandbox(tmp_path)
    # model prints 0 but task asked for 42 — DONE must be blocked once, then fix
    seq = iter([
        '{"action":"write_and_run","path":"h.py","content":"print(0)\\n","command":"python3 h.py"}',
        '{"action":"finish","summary":"done wrong"}',
        '{"action":"write_and_run","path":"h.py","content":"print(42)\\n","command":"python3 h.py"}',
        '{"action":"finish","summary":"prints 42"}',
    ])
    events = list(CodeAgent(sb, lambda m: next(seq), isolated=None).run(
        "make h.py print 42 and run it"))
    kinds = [e["event"] for e in events]
    assert "code_receipt" in kinds
    receipt = [e["data"] for e in events if e["event"] == "code_receipt"][-1]
    assert receipt.get("receipt_sha")
    assert receipt.get("ok") is True
    assert "42" in (receipt.get("last_stdout_tail") or "")
    # blocked the premature DONE
    notes = " ".join(e["data"].get("text", "") for e in events if e["event"] == "agent_note")
    assert "missing expected" in notes or "OUTPUT MISMATCH" in notes or "blocked DONE" in notes
