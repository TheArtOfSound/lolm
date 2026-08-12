from solution import get

data = {
    'a': {'b': 1},
    'items': [{'name': 'first'}, {'name': 'second'}],
    'x': [[0, 1, 2], [3, 4, 5]]
}

# Add more tests
assert get(data, 'a') == {'b': 1}
assert get(data, 'items') == [{'name': 'first'}, {'name': 'second'}]
assert get(data, 'items[0]') == {'name': 'first'}
assert get(data, 'x[0]') == [0, 1, 2]
assert get(data, 'x[0][1]') == 1

print("Additional tests passed!")
