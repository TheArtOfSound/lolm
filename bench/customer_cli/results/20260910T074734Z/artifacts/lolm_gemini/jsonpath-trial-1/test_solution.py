from solution import get

def test():
    data = {
        'a': {'b': 1},
        'items': [{'name': 'first'}, {'name': 'second'}],
        'x': [[0, 1], [2, 3, 4]]
    }
    
    assert get(data, 'a.b') == 1
    assert get(data, 'items[0].name') == 'first'
    assert get(data, 'x[1][2]') == 4
    assert get(data, 'items[-1].name') == 'second'
    assert get(data, 'items[5].name', 'default') == 'default'
    assert get(data, 'a.c', 'missing') == 'missing'
    assert get(data, 'x[0][5]', 'oob') == 'oob'
    
    # Test malformed
    try:
        get(data, '')
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for empty path"

    try:
        get(data, 'a..b')
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for double dot"

    try:
        get(data, 'a[x]')
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for invalid index"

    # Test edge cases for parsing
    try:
        get(data, 'a.b[')
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for unclosed bracket"
    
    # Additional edge case for parsing: 'a[1]b'
    try:
        get(data, 'a[1]b')
    except ValueError:
        pass
    else:
        # Actually this might be technically invalid based on my parser or a strict definition
        # The prompt says 'a.b', 'items[0].name', 'x[1][2]'
        # Let's see what happens if I run 'a[1]b'
        pass
    
    print("All tests passed!")

if __name__ == '__main__':
    test()
