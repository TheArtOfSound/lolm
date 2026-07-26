from local_ui.code_agent import _parse_turn, _wants_tests

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
