from cache import TTLCache
import service

def test_ttl_cache():
    # Test expiration
    c = TTLCache(capacity=2, ttl=5)
    c.set('a', 1, now=10)
    assert c.get('a', now=10) == 1
    assert c.get('a', now=14) == 1
    assert c.get('a', now=15) is None
    assert len(c) == 0

    # Test LRU
    c = TTLCache(capacity=2, ttl=5)
    c.set('a', 1, now=10)
    c.set('b', 2, now=11)
    c.get('a', now=12) # a is now MRU
    c.set('c', 3, now=13) # b should be evicted
    assert c.get('a', now=13) == 1
    assert c.get('b', now=13) is None
    assert c.get('c', now=13) == 3
    print("TTLCache tests passed")

def test_service():
    service.reset()
    
    loader_calls = 0
    def loader(k):
        nonlocal loader_calls
        loader_calls += 1
        return k * 2
    
    # Hit/Miss
    assert service.lookup('a', loader, now=10) == 'aa'
    assert loader_calls == 1
    assert service.lookup('a', loader, now=11) == 'aa'
    assert loader_calls == 1
    assert service.stats() == {'hits': 1, 'misses': 1}
    
    # Expiration
    assert service.lookup('a', loader, now=21) == 'aa'
    assert loader_calls == 2
    
    service.reset()
    assert service.stats() == {'hits': 0, 'misses': 0}
    print("Service tests passed")

if __name__ == "__main__":
    test_ttl_cache()
    test_service()
