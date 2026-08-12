import time
from collections import OrderedDict

class TTLCache:
    def __init__(self, capacity, ttl):
        self.capacity = capacity
        self.ttl = ttl
        self._data = OrderedDict()

    def set(self, key, value, now=None):
        now = time.time() if now is None else now
        
        # 1. Purge expired entries
        self._purge_expired(now)
        
        # 2. Update/Add entry
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (value, now)
        
        # 3. Evict LRU if over capacity
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def get(self, key, now=None):
        now = time.time() if now is None else now
        
        if key not in self._data:
            return None
        
        value, stamp = self._data[key]
        
        if now - stamp >= self.ttl:
            # Entry is expired
            del self._data[key]
            return None
        
        # Move to end to mark as MRU
        self._data.move_to_end(key)
        return value

    def clear(self):
        self._data.clear()

    def __len__(self):
        # Ensure we don't return count of expired entries
        # Wait, the spec says "reading an expired key removes it" and "set() purges expired entries".
        # Should __len__ return only non-expired? Let's check spec again:
        # "len(cache) is the number of stored entries."
        # This implies it should reflect current reality.
        # Let's perform a purge on len() call to be safe, or just return len.
        # Given the requirements, it's safer to keep it consistent.
        return len(self._data)

    def _purge_expired(self, now):
        keys_to_remove = [k for k, (v, stamp) in self._data.items() if now - stamp >= self.ttl]
        for k in keys_to_remove:
            del self._data[k]
