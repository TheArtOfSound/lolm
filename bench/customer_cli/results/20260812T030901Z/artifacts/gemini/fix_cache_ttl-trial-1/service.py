"""Read-through cache in front of a loader."""
from cache import TTLCache

_CACHE = TTLCache(capacity=2, ttl=10)
_HITS = 0
_MISSES = 0


def lookup(key, loader, now=None):
    global _HITS, _MISSES
    if now is None:
        import time
        now = time.time()
    
    hit = _CACHE.get(key, now=now)
    if hit is not None:
        _HITS += 1
        return hit
    
    _MISSES += 1
    value = loader(key)
    _CACHE.set(key, value, now=now)
    return value


def stats():
    return {'hits': _HITS, 'misses': _MISSES}


def reset():
    global _HITS, _MISSES
    _CACHE.clear()
    _HITS = 0
    _MISSES = 0
