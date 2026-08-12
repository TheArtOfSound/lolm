"""Tiny TTL + LRU cache."""
from collections import OrderedDict


class TTLCache:
    def __init__(self, capacity, ttl):
        self.capacity = capacity
        self.ttl = ttl
        self._data = OrderedDict()

    def set(self, key, value, now):
        # 1. Purge expired
        self._purge(now)
        # 2. Add or update key (move to end to maintain LRU)
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (value, now)
        # 3. Evict if still over capacity
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def get(self, key, now):
        if key not in self._data:
            return None
        value, stamp = self._data[key]
        if now - stamp >= self.ttl:
            del self._data[key]
            return None
        # Move to end on hit
        self._data.move_to_end(key)
        return value

    def clear(self):
        self._data.clear()

    def _purge(self, now):
        expired = []
        for k, (_, stamp) in self._data.items():
            if now - stamp >= self.ttl:
                expired.append(k)
            else:
                # Since items are added in order of expiration/access,
                # we can stop early if we assume insertion time correlates with stamp.
                # However, for correctness, check all or keep sorted.
                # Since we use move_to_end, order is not just by stamp.
                pass
        for k in expired:
            del self._data[k]

    def __len__(self):
        return len(self._data)
