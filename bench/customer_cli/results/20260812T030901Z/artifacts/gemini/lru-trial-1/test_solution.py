from solution import LRU

def test_lru():
    # Test basic functionality
    cache = LRU(2)
    cache.put(1, 1)
    cache.put(2, 2)
    assert cache.get(1) == 1
    cache.put(3, 3)
    assert cache.get(2) is None
    assert cache.get(3) == 3
    assert len(cache) == 2
    
    # Test zero capacity
    zero_cache = LRU(0)
    zero_cache.put(1, 1)
    assert zero_cache.get(1) is None
    assert len(zero_cache) == 0
    
    # Test negative capacity
    try:
        LRU(-1)
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for negative capacity"

    print("All tests passed!")

if __name__ == "__main__":
    test_lru()
