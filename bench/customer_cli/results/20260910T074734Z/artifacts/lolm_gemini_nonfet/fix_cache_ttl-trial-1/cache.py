"""Tiny TTL + LRU cache."""
from collections import OrderedDict
import time

class TTLCache:
    def __init__(self, capacity, ttl):
        self.capacity = capacity
        self.ttl = ttl
        self._data = OrderedDict()

    def _purge(self, now):
        expired = [k for k, (v, stamp) in self._data.items() if now - stamp >= self.ttl]
        for k in expired:
            del self._data[k]

    def set(self, key, value, now=None):
        now = time.time() if now is None else now
        
        # Purge expired entries first
        self._purge(now)
        
        if key in self._data:
            self._data.move_to_end(key)
        
        self._data[key] = (value, now)
        
        if len(self._data) > self.capacity:
            # Evict LRU
            self._data.popitem(last=False)

    def get(self, key, now=None):
        now = time.time() if now is None else now
        
        if key not in self._data:
            return None
        
        value, stamp = self._data[key]
        if now - stamp >= self.ttl:
            del self._data[key]
            return None
        
        self._data.move_to_end(key)
        return value

    def clear(self):
        self._data.clear()

    def __len__(self):
        self._purge(time.time())
        return len(self._data)
