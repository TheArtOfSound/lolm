from solution import get

def test_malformed_bracket():
    data = {'a': 1}
    try:
        get(data, 'a[x]')
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for a[x]"

def test_malformed_dot():
    data = {'a': 1}
    try:
        get(data, 'a..b')
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for a..b"

test_malformed_bracket()
test_malformed_dot()
print("All malformed tests passed!")
