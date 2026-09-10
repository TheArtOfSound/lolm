from solution import get

# Test cases
data = {
    'a': {'b': 1},
    'items': [{'name': 'first'}, {'name': 'second'}],
    'x': [[0, 1, 2], [3, 4, 5]]
}

assert get(data, 'a.b') == 1
assert get(data, 'items[0].name') == 'first'
assert get(data, 'x[1][2]') == 5
assert get(data, 'x[1][-1]') == 5
assert get(data, 'missing', 'default') == 'default'
assert get(data, 'a.c', 'default') == 'default'
assert get(data, 'items[5]', 'default') == 'default'

# Malformed paths
try:
    get(data, '')
    assert False, "Should raise ValueError for empty path"
except ValueError:
    pass

try:
    get(data, 'a..b')
    assert False, "Should raise ValueError for a..b"
except ValueError:
    pass

try:
    get(data, 'a[x]')
    assert False, "Should raise ValueError for a[x]"
except ValueError:
    pass

print("All tests passed!")
