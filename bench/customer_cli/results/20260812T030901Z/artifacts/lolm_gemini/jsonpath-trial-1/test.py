from solution import get

# Test cases
data = {
    'a': {'b': 1},
    'items': [{'name': 'first'}, {'name': 'second'}],
    'x': [[0, 1, 2], [3, 4, 5]]
}

assert get(data, 'a.b') == 1
assert get(data, 'items[0].name') == 'first'
assert get(data, 'items[1].name') == 'second'
assert get(data, 'x[1][2]') == 5
assert get(data, 'x[1][-1]') == 5
assert get(data, 'items[5].name', 'default') == 'default'
assert get(data, 'a.c', 'default') == 'default'
assert get(data, 'a[0]', 'default') == 'default'

# Malformed paths
try:
    get(data, '')
except ValueError:
    pass
else:
    assert False, "Should have raised ValueError"

try:
    get(data, 'a..b')
except ValueError:
    pass
else:
    assert False, "Should have raised ValueError"

try:
    get(data, 'a[x]')
except ValueError:
    pass
else:
    assert False, "Should have raised ValueError"

print("All tests passed!")
