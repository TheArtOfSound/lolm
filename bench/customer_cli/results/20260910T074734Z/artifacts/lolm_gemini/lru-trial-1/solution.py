class LRU:
    def __init__(self, capacity):
        if capacity < 0:
            raise ValueError("Capacity cannot be negative")
        self.capacity = capacity
        self.cache = {}

    def __len__(self):
        return len(self.cache)

    def get(self, key):
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        return None

    def put(self, key, value):
        if self.capacity == 0:
            return
        if key in self.cache:
            self.cache.pop(key)
        elif len(self.cache) >= self.capacity:
            oldest_key = next(iter(self.cache))
            self.cache.pop(oldest_key)
        
        self.cache[key] = value
