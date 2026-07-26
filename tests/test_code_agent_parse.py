from local_ui.code_agent import (
    _parse_turn, _wants_tests, _pick_verify_command, _is_test_path,
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
