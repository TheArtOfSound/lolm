from solution import LRU

def test_lru():
    # Test capacity 0
    lru0 = LRU(0)
    lru0.put(1, 100)
    assert len(lru0) == 0
    assert lru0.get(1) is None
    print("Capacity 0 test passed.")

    # Test basic functionality
    lru = LRU(2)
    lru.put(1, 1)
    lru.put(2, 2)
    assert len(lru) == 2
    assert lru.get(1) == 1
    lru.put(3, 3) # Should evict 2
    assert lru.get(2) is None
    assert lru.get(1) == 1
    assert lru.get(3) == 3
    print("Basic functionality test passed.")

    # Test order
    lru = LRU(2)
    lru.put(1, 1)
    lru.put(2, 2)
    lru.get(1) # Make 1 MRU
    lru.put(3, 3) # Should evict 2
    assert lru.get(2) is None
    assert lru.get(1) == 1
    assert lru.get(3) == 3
    print("Ordering test passed.")

    # Test ValueError
    try:
        LRU(-1)
        assert False, "Should have raised ValueError"
    except ValueError:
        print("ValueError test passed.")

if __name__ == "__main__":
    test_lru()
