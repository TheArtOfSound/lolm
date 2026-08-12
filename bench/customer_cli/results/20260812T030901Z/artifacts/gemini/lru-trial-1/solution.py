class LRU:
    def __init__(self, capacity):
        if capacity < 0:
            raise ValueError("Capacity cannot be negative")
        self.capacity = capacity
        self.cache = {}
        # Using a list to maintain order is inefficient for large caches,
        # but Python's dict maintains insertion order since 3.7.
        # However, for true LRU (move to end on access), we need to re-insert.

    def get(self, key):
        if key not in self.cache:
            return None
        # Move to end to mark as most recently used
        val = self.cache.pop(key)
        self.cache[key] = val
        return val

    def put(self, key, value):
        if self.capacity == 0:
            return
        
        if key in self.cache:
            self.cache.pop(key)
        elif len(self.cache) >= self.capacity:
            # Evict least recently used (first item in dict)
            first_key = next(iter(self.cache))
            self.cache.pop(first_key)
        
        self.cache[key] = value

    def __len__(self):
        return len(self.cache)
