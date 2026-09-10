"""Read-through cache in front of a loader."""
from cache import TTLCache

_CACHE = TTLCache(capacity=2, ttl=10)


def lookup(key, loader, now=None):
    hit = _CACHE.get(key, now=now)
    if hit is not None:
        return hit
    value = loader(key)
    _CACHE.set(key, value, now=now)
    return value
