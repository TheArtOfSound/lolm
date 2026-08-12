"""Read-through cache in front of a loader."""
from cache import TTLCache

_CACHE = TTLCache(capacity=2, ttl=10)
_STATS = {'hits': 0, 'misses': 0}

def lookup(key, loader, now=None):
    hit = _CACHE.get(key, now=now)
    if hit is not None:
        _STATS['hits'] += 1
        return hit
    
    _STATS['misses'] += 1
    value = loader(key)
    _CACHE.set(key, value, now=now)
    return value

def stats():
    return _STATS.copy()

def reset():
    _CACHE.clear()
    _STATS['hits'] = 0
    _STATS['misses'] = 0
