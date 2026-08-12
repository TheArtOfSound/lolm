import cache
import service

def test_cache():
    # TTL and expiration test
    c = cache.TTLCache(capacity=2, ttl=10)
    c.set('a', 1, now=100)
    assert c.get('a', now=105) == 1
    assert c.get('a', now=110) is None  # exactly at ttl
    assert len(c) == 0
    
    # Capacity and LRU
    c = cache.TTLCache(capacity=2, ttl=10)
    c.set('a', 1, now=100)
    c.set('b', 2, now=100)
    c.set('c', 3, now=100) # Should evict 'a' (LRU)
    assert c.get('a', now=100) is None
    assert c.get('b', now=100) == 2
    assert c.get('c', now=100) == 3
    
    # Expired entry eviction in set
    c = cache.TTLCache(capacity=2, ttl=10)
    c.set('a', 1, now=100)
    c.set('b', 2, now=100)
    c.set('c', 3, now=115) # 'a' and 'b' expired, 'c' added, size should be 1
    assert len(c) == 1
    assert c.get('c', now=115) == 3

def test_service():
    service.reset()
    loader_calls = 0
    def loader(k):
        nonlocal loader_calls
        loader_calls += 1
        return k * 10
    
    assert service.lookup('a', loader, now=100) == 'a' * 10
    assert loader_calls == 1
    assert service.stats() == {'hits': 0, 'misses': 1}
    
    assert service.lookup('a', loader, now=105) == 'a' * 10
    assert loader_calls == 1
    assert service.stats() == {'hits': 1, 'misses': 1}
    
    assert service.lookup('b', loader, now=105) == 'b' * 10
    assert loader_calls == 2
    
    service.reset()
    assert service.stats() == {'hits': 0, 'misses': 0}

if __name__ == "__main__":
    test_cache()
    test_service()
    print("All tests passed!")
