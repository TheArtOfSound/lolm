# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for what the coding loop actually SHOWS the model each turn.

These cover the defects a hidden-test benchmark caught: the loop hard-coded
`FILE: main.py` in its own scaffold (so a task naming solution.py produced an
unimportable main.py), and it never put the current file contents in context (so a
blind full rewrite was the only move the model could make).
"""

from local_ui.code_agent import (
    CodeAgent,
    _is_test_command,
    _pick_verify_command,
    _task_target_files,
)
from local_ui.sandbox import Sandbox


def _agent(tmp_path):
    return CodeAgent(Sandbox(tmp_path), lambda msgs: "", isolated=None)


# ── the scaffold must name the task's own files ──────────────────────────────

def test_task_target_files_picks_named_paths_in_order():
    assert _task_target_files("Create solution.py defining f()") == ["solution.py"]
    assert _task_target_files("fix stats.py, then report.py uses it") == [
        "stats.py", "report.py"]
    assert _task_target_files("no files here") == []
    # A duration literal is not a filename, and neither is prose punctuation.
    assert _task_target_files("parse 'P3DT4H5M6S' e.g. quickly") == []


def test_first_turn_scaffold_uses_the_requested_path_not_main_py(tmp_path):
    ctx = _agent(tmp_path)._context("Create solution.py defining parse(s)")
    assert "FILE: solution.py" in ctx
    assert "RUN: python3 solution.py" in ctx
    assert "main.py" not in ctx


def test_first_turn_scaffold_lists_every_requested_path(tmp_path):
    ctx = _agent(tmp_path)._context("stats.py provides median; report.py summarizes")
    assert "stats.py" in ctx and "report.py" in ctx
    assert "create EVERY one" in ctx


def test_first_turn_falls_back_to_main_py_when_no_path_named(tmp_path):
    ctx = _agent(tmp_path)._context("print the first 10 primes")
    assert "FILE: main.py" in ctx


# ── the model must see the code it is editing ────────────────────────────────

def test_workspace_block_shows_real_on_disk_content(tmp_path):
    a = _agent(tmp_path)
    a.sb.write_file("solution.py", "def f():\n    return 41\n")
    ctx = a._context("fix f to return 42")
    assert "CURRENT WORKSPACE" in ctx
    assert "return 41" in ctx, "the model must see the actual code, not just a byte count"


def test_workspace_block_has_no_line_numbers(tmp_path):
    # EDIT matches by exact substring, so a gutter number copied into the old text
    # would guarantee a miss on every edit.
    a = _agent(tmp_path)
    a.sb.write_file("solution.py", "alpha\nbeta\n")
    ctx = a._context("x")
    assert "\nalpha\n" in ctx
    assert "1: alpha" not in ctx and "1|alpha" not in ctx


def test_workspace_block_skips_bytecode(tmp_path):
    a = _agent(tmp_path)
    a.sb.write_file("solution.py", "x = 1\n")
    a.sb.write_file("__pycache__/solution.cpython-312.pyc", "\x00\x01binary")
    ctx = a._context("x")
    assert "solution.py" in ctx
    assert "__pycache__" not in ctx and "binary" not in ctx


def test_existing_files_are_repaired_not_overwritten(tmp_path):
    # A fix task starts with files already present. The old scaffold told the model
    # "nothing run yet, write the complete program", which invited it to clobber the
    # very code it was asked to repair.
    a = _agent(tmp_path)
    a.sb.write_file("paginate.py", "def page_items(items, page, per_page):\n    pass\n")
    ctx = a._context("paginate.py has bugs — fix page_items")
    assert "ALREADY EXIST" in ctx
    assert "Nothing run yet" not in ctx
    assert "def page_items" in ctx


def test_workspace_block_is_budgeted_and_marks_elision(tmp_path):
    a = _agent(tmp_path)
    a.sb.write_file("big.py", "# pad\n" * 4000)
    ctx = a._context("x")
    assert len(ctx) < 4 * a._WS_BUDGET, "unbounded context would push SYSTEM out of the window"
    assert "chars omitted" in ctx


# ── history window must keep the informative rows ────────────────────────────

def test_recent_actions_drops_green_verifies_but_keeps_failing_ones(tmp_path):
    a = _agent(tmp_path)
    a.actions = [
        {"kind": "run", "command": "python3 -m py_compile x.py", "verify": True,
         "result": {"exit_code": 0}},
        {"kind": "run", "command": "python3 -m unittest -q t", "verify": True,
         "result": {"exit_code": 1, "stderr": "FAILED (failures=1)"}},
        {"kind": "write_file", "path": "x.py", "bytes": 10},
    ]
    kept = a._recent_actions()
    cmds = [x.get("command") for x in kept]
    assert "python3 -m py_compile x.py" not in cmds, "a green py_compile carries no signal"
    assert "python3 -m unittest -q t" in cmds, "a FAILING verify is the most informative row"
    assert len(kept) == 2


def test_recent_actions_window_is_wider_than_eight(tmp_path):
    a = _agent(tmp_path)
    a.actions = [{"kind": "write_file", "path": f"f{i}.py", "bytes": 1} for i in range(20)]
    assert len(a._recent_actions()) == 12


def test_edit_miss_steers_to_the_workspace_block(tmp_path):
    a = _agent(tmp_path)
    a.sb.write_file("x.py", "def f():\n    return 1\n")
    seq = iter([
        "EDIT: x.py\n<<<\nreturn 999\n===\nreturn 2\n>>>",
        "DONE: gave up",
    ])
    a.chat = lambda msgs: next(seq)
    list(a.run("change the return value"))
    miss = [x for x in a.actions if x.get("kind") == "edit_file" and not x.get("ok")]
    assert miss, "expected the failed edit to be recorded"
    note = miss[0]["note"]
    assert "CURRENT WORKSPACE" in note and "NOTHING changed" in note
    assert a.sb.read_file("x.py") == "def f():\n    return 1\n", "a missed edit must not write"


# ── the test oracle must be runnable ────────────────────────────────────────

def test_verify_command_names_test_modules_explicitly():
    # `discover -p 'test*.py'` collects nothing for foo_test.py and then exits 5
    # (NO TESTS RAN), so the verify could never go green however correct the code was.
    cmd = _pick_verify_command(["solution.py", "solution_test.py"], "add tests")
    assert "discover" not in cmd
    assert "python3 -m unittest -q solution_test" in cmd
    assert "pytest" in cmd, "pytest is still preferred when the jail happens to have it"


def test_verify_command_handles_nested_test_paths():
    cmd = _pick_verify_command(["tests/test_x.py"], "add tests")
    assert "tests.test_x" in cmd


def test_is_test_command():
    assert _is_test_command("python3 -m unittest -q t")
    assert _is_test_command("python3 -m pytest -q")
    assert not _is_test_command("python3 solution.py")


def test_green_test_run_counts_as_output_even_with_empty_stdout(tmp_path):
    # unittest reports "Ran N tests / OK" on STDERR. Counting only stdout made a
    # genuinely passing suite look like it printed nothing, which blocked DONE and
    # recorded a correct run as incomplete.
    sb = Sandbox(tmp_path)
    sb.write_file("test_s.py", "import unittest\n"
                               "class T(unittest.TestCase):\n"
                               "    def test_ok(self):\n"
                               "        self.assertEqual(1, 1)\n")
    seq = iter([
        "RUN: python3 -m unittest -q test_s",
        "DONE: tests pass",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    events = list(agent.run("run the tests in test_s.py"))
    done = [e["data"] for e in events if e["event"] == "code_done"][0]
    assert done["produced_output"] is True
    assert done["ran"] is True


# ── the requested path is a contract, not a suggestion ───────────────────────

def test_done_blocked_until_the_required_file_exists(tmp_path):
    # Correct code at the wrong path is a total failure — the caller imports exactly
    # what the task named. This used to sail straight through as a green DONE.
    sb = Sandbox(tmp_path)
    seq = iter([
        "FILE: mycache.py\n```\ndef f():\n    return 1\nprint(f())\n```\nRUN: python3 mycache.py",
        "DONE: built it",
        "FILE: solution.py\n```\ndef f():\n    return 1\nprint(f())\n```\nRUN: python3 solution.py",
        "DONE: at the right path now",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    events = list(agent.run("Create solution.py defining f()"))
    notes = [e["data"].get("text", "") for e in events if e["event"] == "agent_note"]
    assert any("required file missing" in n for n in notes), notes
    assert "solution.py" in sb.list_files()
    done = [e["data"] for e in events if e["event"] == "code_done"]
    assert done and done[0]["summary"], "should still finish once the path is right"


def test_missing_targets_reports_only_absent_paths(tmp_path):
    a = _agent(tmp_path)
    a.sb.write_file("stats.py", "x = 1\n")
    assert a._missing_targets("fix stats.py and report.py") == ["report.py"]
    assert a._missing_targets("no filenames named here") == []
    a.sb.write_file("report.py", "y = 2\n")
    assert a._missing_targets("fix stats.py and report.py") == []


# ── never report DONE over code that does not compile ────────────────────────

def test_broken_final_tree_is_reported_as_broken_not_shipped(tmp_path):
    # The write-time preflight can be left behind when the step budget runs out
    # mid-repair. The loop used to hand back a tree with a SyntaxError in it and
    # still call it shipped — the one failure a receipts product cannot afford.
    sb = Sandbox(tmp_path)
    seq = iter([
        "FILE: solution.py\n```\nprint('hi')\n```\nRUN: python3 solution.py",
        "FILE: solution.py\n```\ndef broken(:\n```\nRUN: python3 solution.py",
        "DONE: shipped it",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    events = list(agent.run("Create solution.py"))
    rec = [e["data"] for e in events if e["event"] == "code_receipt"][0]
    assert rec["syntax_ok"] is False, rec.get("syntax_error")
    assert rec["ok"] is False, "broken code must never read as ok"
    assert rec["verdict"] == "broken", rec["verdict"]
    assert "solution.py" in rec["syntax_checked"]
    # the seal must cover the syntax verdict, not be bolted on after hashing
    import json, hashlib
    core = {k: v for k, v in rec.items() if k not in ("receipt_sha", "verdict")}
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(blob.encode()).hexdigest()[:24] == rec["receipt_sha"], \
        "receipt_sha must cover syntax_ok"


def test_compiling_code_still_reports_shipped(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        "FILE: solution.py\n```\ndef f():\n    return 42\nprint(f())\n```\nRUN: python3 solution.py",
        "DONE: works",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    events = list(agent.run("Create solution.py defining f()"))
    rec = [e["data"] for e in events if e["event"] == "code_receipt"][0]
    assert rec["syntax_ok"] is True
    assert rec["ok"] is True and rec["verdict"] == "shipped", rec["verdict"]


# ── the required NAME is a contract too ──────────────────────────────────────

def test_required_symbols_reads_only_the_definitional_clause():
    from local_ui.code_agent import _task_required_symbols as sym
    assert sym("Create solution.py defining parse_duration(s) -> float") == ["parse_duration"]
    assert sym("defining to_roman(n) -> str and from_roman(s) -> int") == [
        "to_roman", "from_roman"]
    # A class's methods live on the instance, not the module — requiring them at module
    # level would deadlock the loop against a requirement the task never made.
    assert sym("defining a class LRU(capacity) implementing a cache with get(key) "
               "and put(key, value)") == ["LRU"]


def test_prose_cannot_manufacture_a_required_symbol():
    from local_ui.code_agent import _task_required_symbols as sym
    # A space before the paren means prose, not a signature.
    assert sym("defining merge(intervals) over [start, end] pairs (unsorted)") == ["merge"]
    assert sym("defining to_roman(n) using subtractive forms (IV, IX)") == ["to_roman"]
    assert sym("no definitional cue here foo(bar)") == []
    assert sym("") == []


def test_done_blocked_until_the_required_name_exists(tmp_path):
    sb = Sandbox(tmp_path)
    seq = iter([
        # right file, wrong name — used to sail through as a green DONE
        "FILE: solution.py\n```\ndef calc(s):\n    return 1.0\nprint(calc('x'))\n```\n"
        "RUN: python3 solution.py",
        "DONE: built the evaluator",
        "FILE: solution.py\n```\ndef evaluate(s):\n    return 1.0\nprint(evaluate('x'))\n```\n"
        "RUN: python3 solution.py",
        "DONE: named correctly now",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    events = list(agent.run("Create solution.py defining evaluate(s) -> float"))
    notes = [e["data"].get("text", "") for e in events if e["event"] == "agent_note"]
    assert any("required name missing" in n for n in notes), notes
    assert "def evaluate" in sb.read_file("solution.py")


def test_done_blocked_while_the_tree_does_not_compile(tmp_path):
    # The finish-time check keeps the receipt honest; this gate actually gets the code
    # fixed while budget remains, instead of handing back a broken tree.
    sb = Sandbox(tmp_path)
    seq = iter([
        "FILE: solution.py\n```\nprint('ok')\n```\nRUN: python3 solution.py",
        "FILE: solution.py\n```\ndef broken(:\n```\nRUN: python3 solution.py",
        "DONE: shipping it",
        "FILE: solution.py\n```\ndef fixed():\n    return 1\nprint(fixed())\n```\n"
        "RUN: python3 solution.py",
        "DONE: compiles now",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None)
    events = list(agent.run("Create solution.py"))
    notes = [e["data"].get("text", "") for e in events if e["event"] == "agent_note"]
    assert any("does not compile" in n for n in notes), notes
    rec = [e["data"] for e in events if e["event"] == "code_receipt"][-1]
    assert rec["syntax_ok"] is True, "it should have been driven to a compiling tree"


# ── best-of-N on the opening turn ────────────────────────────────────────────

def test_ensemble_keeps_the_candidate_that_actually_runs(tmp_path):
    # Scored by what happens when the code RUNS, not by how the text reads: the
    # broken candidate compiles-fails, the wrong-path one misses the contract.
    sb = Sandbox(tmp_path)
    cands = [
        {"model": "broken", "text": "FILE: solution.py\n```\ndef f(:\n```\nRUN: python3 solution.py"},
        {"model": "wrongpath", "text": "FILE: other.py\n```\ndef go():\n    return 1\nprint(go())\n```\nRUN: python3 other.py"},
        {"model": "good", "text": "FILE: solution.py\n```\ndef go():\n    return 7\nprint(go())\n```\nRUN: python3 solution.py"},
    ]
    agent = CodeAgent(sb, lambda m: "DONE: fallback", isolated=None,
                      gen_many_fn=lambda msgs, models: cands)
    events = list(agent.run("Create solution.py defining go()"))
    notes = [e["data"] for e in events if e["event"] == "agent_note"
             and "raced" in (e["data"].get("text") or "")]
    assert notes, "expected an ensemble note"
    scores = {c["model"]: c["score"] for c in notes[0]["candidates"]}
    assert scores["good"] > scores["broken"], scores
    assert scores["good"] > scores["wrongpath"], scores
    assert scores["broken"] == 0.0, "code that does not compile scores zero"
    assert "def go" in sb.read_file("solution.py")


def test_ensemble_failure_falls_back_to_the_single_model(tmp_path):
    sb = Sandbox(tmp_path)
    def boom(msgs, models):
        raise RuntimeError("gateway down")
    seq = iter([
        "FILE: solution.py\n```\ndef go():\n    return 1\nprint(go())\n```\nRUN: python3 solution.py",
        "DONE: ok",
    ])
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None, gen_many_fn=boom)
    events = list(agent.run("Create solution.py defining go()"))
    assert any(e["event"] == "code_done" for e in events), "must not die with the gateway"
    assert "def go" in sb.read_file("solution.py")


def test_ensemble_only_runs_on_the_first_turn(tmp_path):
    sb = Sandbox(tmp_path)
    calls = {"n": 0}
    def many(msgs, models):
        calls["n"] += 1
        return [{"model": "m", "text": "FILE: solution.py\n```\nprint(1)\n```\nRUN: python3 solution.py"}]
    seq = iter(["DONE: done"] * 6)
    agent = CodeAgent(sb, lambda m: next(seq), isolated=None, gen_many_fn=many)
    list(agent.run("Create solution.py"))
    assert calls["n"] == 1, f"ensemble should fire once, fired {calls['n']}x"
