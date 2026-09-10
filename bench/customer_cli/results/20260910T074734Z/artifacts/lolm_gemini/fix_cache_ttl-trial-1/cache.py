import collections

class TTLCache:
    def __init__(self, capacity, ttl):
        self.capacity = capacity
        self.ttl = ttl
        self._data = collections.OrderedDict()

    def set(self, key, value, now):
        # 1. Purge expired entries
        # Important: only those that are definitely expired.
        for k in list(self._data.keys()):
            _, stored_at = self._data[k]
            if (now - stored_at) >= self.ttl:
                del self._data[k]

        # 2. If it exists, remove it first
        if key in self._data:
            self._data.pop(key)
        
        # 3. If at capacity, evict LRU
        if len(self._data) >= self.capacity:
            self._data.popitem(last=False)
            
        self._data[key] = (value, now)

    def get(self, key, now):
        if key not in self._data:
            return None
        
        value, stored_at = self._data[key]
        if (now - stored_at) >= self.ttl:
            del self._data[key]
            return None
        
        # Move to end (MRU)
        self._data.move_to_end(key)
        return value

    def clear(self):
        self._data.clear()

    def __len__(self):
        return len(self._data)
