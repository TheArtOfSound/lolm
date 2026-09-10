from topo import toposort, CycleError

def test():
    # Basic
    assert toposort({}) == []
    assert toposort({'a': ['b'], 'b': []}) == ['b', 'a']
    assert toposort({'a': ['b', 'c'], 'b': ['c'], 'c': []}) == ['c', 'b', 'a']
    
    # Tie-breaking (deterministic)
    # Both 1 and 2 are ready. Should pick 1.
    assert toposort({3: [1, 2], 1: [], 2: []}) == [1, 2, 3]
    
    # Cycle detection
    try:
        toposort({'a': ['b'], 'b': ['a']})
    except CycleError as e:
        assert e.cycle in (['a', 'b', 'a'], ['b', 'a', 'b'])
    else:
        assert False, "Should have raised CycleError"

    print("All tests passed!")

if __name__ == "__main__":
    test()
