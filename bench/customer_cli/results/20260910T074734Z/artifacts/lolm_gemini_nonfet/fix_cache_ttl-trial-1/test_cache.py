from cache import TTLCache

def test_ttl_cache():
    # Test expiration: now - stored_at >= ttl is expired
    c = TTLCache(capacity=2, ttl=10)
    c.set('k', 'v', now=100)
    assert c.get('k', now=110) is None, "Should be expired at exactly TTL"
    assert c.get('k', now=109) == 'v', "Should be alive before TTL"
    
    # After checking get(110), it should be removed
    assert len(c) == 0, "Expired key should be removed"

    # Test MRU
    c = TTLCache(capacity=2, ttl=10)
    c.set('a', 1, now=100)
    c.set('b', 2, now=100)
    c.get('a', now=100) # Access a, a is now MRU
    c.set('c', 3, now=100) # Should evict b (least recently used)
    assert c.get('a', now=100) == 1
    assert c.get('c', now=100) == 3
    assert c.get('b', now=100) is None

    # Test purge first then evict
    c = TTLCache(capacity=1, ttl=10)
    c.set('a', 1, now=100)
    c.set('b', 2, now=115) # a is expired (115 - 100 = 15 > 10), set('b') should purge 'a' first
    assert len(c) == 1
    assert c.get('b', now=115) == 2
    
    c.clear()
    assert len(c) == 0

    print("TTLCache tests passed")

test_ttl_cache()
