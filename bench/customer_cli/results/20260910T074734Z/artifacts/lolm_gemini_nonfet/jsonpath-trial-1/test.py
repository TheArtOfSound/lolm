from solution import get

# Tests
data = {
    'a': {'b': 1},
    'items': [{'name': 'first'}, {'name': 'second'}],
    'x': [[0, 1, 2], [3, 4, 5]]
}

assert get(data, 'a.b') == 1
assert get(data, 'items[0].name') == 'first'
assert get(data, 'x[1][2]') == 5
assert get(data, 'x[1][-1]') == 5
assert get(data, 'a.c', default='missing') == 'missing'
assert get(data, 'items[5].name', default='none') == 'none'

# Check ValueError
def check_malformed(path):
    try:
        get(data, path)
        print(f"Failed to catch malformed: {path}")
    except ValueError:
        pass

check_malformed('')
check_malformed('a..b')
check_malformed('a[x]')
check_malformed('a[0]b')
check_malformed('.a')
check_malformed('a.')

print("All tests passed!")
