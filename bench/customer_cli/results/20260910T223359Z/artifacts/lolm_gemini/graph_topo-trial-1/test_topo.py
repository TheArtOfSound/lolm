from topo import toposort, CycleError

def test():
    # Test 1: Simple
    assert toposort({'a': ['b'], 'b': []}) == ['b', 'a']
    
    # Test 2: Deterministic choice (b and c are both ready, pick b)
    # Graph: a depends on [b, c]
    # Ready nodes: b, c. Should pick b then c, then a.
    assert toposort({'a': ['b', 'c']}) == ['b', 'c', 'a']
    
    # Test 3: Empty
    assert toposort({}) == []
    
    # Test 4: Nodes appearing only as dependencies
    # Graph: {'a': ['b']}
    assert toposort({'a': ['b']}) == ['b', 'a']
    
    # Test 5: Cycle
    try:
        toposort({'a': ['b'], 'b': ['a']})
    except CycleError as e:
        print(f"Caught expected cycle: {e.cycle}")
        assert e.cycle[0] == e.cycle[-1]
    else:
        assert False, "Did not raise CycleError"
        
    print("All tests passed!")

if __name__ == "__main__":
    test()
