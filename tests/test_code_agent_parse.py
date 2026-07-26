from local_ui.code_agent import (
    _parse_turn, _wants_tests, _pick_verify_command, _is_test_path,
    _expected_outputs,
)

def test_multi_file():
    text = '''FILE: a.py
```
print(1)
```
FILE: b.py
```
print(2)
```
RUN: python3 a.py
'''
    t = _parse_turn(text)
    assert t is not None
    assert len(t["files"]) == 2
    assert t["run"].startswith("python3")

def test_wants_tests():
    assert _wants_tests("write unit tests for fib")
    assert not _wants_tests("print hello")


def test_is_test_path():
    assert _is_test_path("test_math.py")
    assert _is_test_path("util_test.py")
    assert _is_test_path("tests/test_a.py")
    assert not _is_test_path("main.py")


def test_pick_verify_prefers_test_oracle():
    cmd = _pick_verify_command(["main.py", "test_main.py"], "add tests")
    assert cmd is not None
    assert "unittest discover" in cmd or "pytest" in cmd
    assert "test_main.py" in cmd or "test*.py" in cmd


def test_pick_verify_py_compile_for_multi_file():
    cmd = _pick_verify_command(["a.py", "b.py"], "build a small package")
    assert cmd is not None
    assert "py_compile" in cmd
    assert "a.py" in cmd and "b.py" in cmd


def test_pick_verify_skips_trivial_single_file():
    assert _pick_verify_command(["main.py"], "print hello") is None


def test_json_write_and_run_single():
    t = _parse_turn('{"action":"write_and_run","path":"x.py","content":"print(1)\\n","command":"python3 x.py"}')
    assert t is not None
    assert t["files"][0][0] == "x.py"
    assert t["run"] == "python3 x.py"


def test_json_multi_actions():
    text = '''{"actions":[
      {"action":"write_file","path":"a.py","content":"print(2)\\n"},
      {"action":"run","command":"python3 a.py"}
    ]}'''
    t = _parse_turn(text)
    assert t is not None
    assert len(t["files"]) == 1 and t["files"][0][0] == "a.py"
    assert t["run"] == "python3 a.py"


def test_json_read_and_edit():
    t = _parse_turn('{"action":"read_file","path":"main.py"}')
    assert t and t["reads"] == ["main.py"]
    t2 = _parse_turn('{"action":"edit_file","path":"main.py","old":"foo","new":"bar"}')
    assert t2 and t2["edits"][0] == ("main.py", "foo", "bar")


def test_text_read_and_edit_blocks():
    text = '''READ: main.py
EDIT: main.py
<<<
prnt(1)
===
print(1)
>>>
RUN: python3 main.py
'''
    t = _parse_turn(text)
    assert t is not None
    assert "main.py" in t["reads"]
    assert t["edits"][0][0] == "main.py"
    assert t["edits"][0][2] == "print(1)"
    assert t["run"].startswith("python3")


def test_expected_outputs_from_task():
    assert "42" in _expected_outputs("make hello.py print 42 and run it")
    assert "hello" in _expected_outputs('print the string "hello"')
