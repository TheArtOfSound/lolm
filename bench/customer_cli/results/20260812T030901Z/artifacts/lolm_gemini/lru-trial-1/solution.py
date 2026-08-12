class LRU:
    def __init__(self, capacity):
        if capacity < 0:
            raise ValueError("Capacity cannot be negative")
        self.capacity = capacity
        from collections import OrderedDict
        self.cache = OrderedDict()

    def __len__(self):
        return len(self.cache)

    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key, value):
        if self.capacity == 0:
            return
        
        if key in self.cache:
            self.cache.move_to_end(key)
            self.cache[key] = value
        else:
            if len(self.cache) >= self.capacity:
                self.cache.popitem(last=False)
            self.cache[key] = value
