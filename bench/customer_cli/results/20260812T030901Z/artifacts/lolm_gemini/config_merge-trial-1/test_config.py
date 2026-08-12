from config import merge

def test():
    # Base cases
    b1 = {'a': 1, 'b': {'c': 2}}
    o1 = {'a': 2, 'b': {'d': 3}}
    assert merge(b1, o1) == {'a': 2, 'b': {'c': 2, 'd': 3}}
    
    # List strategies
    b2 = {'l': [1, 2]}
    o2 = {'l': [3, 4]}
    assert merge(b2, o2, list_strategy='replace') == {'l': [3, 4]}
    assert merge(b2, o2, list_strategy='append') == {'l': [1, 2, 3, 4]}
    
    b3 = {'l': [1, 2, 2]}
    o3 = {'l': [2, 3]}
    assert merge(b3, o3, list_strategy='unique') == {'l': [1, 2, 3]}
    
    # Numbers
    assert merge({'a': 1}, {'a': 1.5}) == {'a': 1.5}
    
    # Conflict path check
    try:
        merge({'x': {'y': 1}}, {'x': {'y': 'str'}})
    except ValueError as e:
        assert "x.y" in str(e)
    
    # Boolean vs Number
    try:
        merge({'a': 1}, {'a': True})
    except ValueError as e:
        assert "a" in str(e)
    
    # Strategy error
    try:
        merge({'l': []}, {'l': []}, list_strategy='invalid')
    except ValueError as e:
        assert "invalid" in str(e)

    # Immutability
    b4 = {'a': 1}
    o4 = {'b': 2}
    res = merge(b4, o4)
    assert b4 == {'a': 1}
    assert o4 == {'b': 2}
    assert res == {'a': 1, 'b': 2}
    
    # Test path with empty dict
    b5 = {}
    o5 = {'a': 1}
    assert merge(b5, o5) == {'a': 1}

    print("All tests passed!")

if __name__ == "__main__":
    test()
