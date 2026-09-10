from solution import parse_duration

def test(s, expected):
    result = parse_duration(s)
    assert result == expected, f"Expected {expected}, got {result}"

test('P3DT4H5M6S', 273906.0)
test('PT0.5S', 0.5)
test('P1Y', 31536000.0)
test('-PT5M', -300.0)
test('PT1H', 3600.0)
print("All tests passed")
