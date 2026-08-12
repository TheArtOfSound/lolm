from csvlite import parse

test_cases = [
    ("a,b,c", [["a", "b", "c"]]),
    ("a,\"b,c\",d", [["a", "b,c", "d"]]),
    ("a,\"\"\"quoted\"\"\",d", [["a", "\"quoted\"", "d"]]),
    ("a,,c", [["a", "", "c"]]),
    ("a\nb", [["a"], ["b"]]),
    ("a,b\n", [["a", "b"]]),
    ("a,b\nc,d\n", [["a", "b"], ["c", "d"]]),
    ("", []),
]

for i, (text, expected) in enumerate(test_cases):
    result = parse(text)
    assert result == expected, f"Test {i} failed: expected {expected}, got {result}"
    print(f"Test {i} passed")
