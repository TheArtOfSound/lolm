import unittest
from cache import TTLCache
import service

class TestCache(unittest.TestCase):
    def test_ttl(self):
        c = TTLCache(2, 10)
        c.set('a', 1, now=100)
        self.assertEqual(c.get('a', now=109), 1)
        self.assertEqual(c.get('a', now=110), None)
        self.assertEqual(len(c), 0)

    def test_lru(self):
        c = TTLCache(2, 10)
        c.set('a', 1, now=100)
        c.set('b', 2, now=100)
        c.get('a', now=101) # a is now MRU
        c.set('c', 3, now=100)
        self.assertEqual(c.get('b', now=100), None)
        self.assertEqual(c.get('a', now=100), 1)
        self.assertEqual(c.get('c', now=100), 3)

    def test_purge_on_set(self):
        c = TTLCache(2, 10)
        c.set('a', 1, now=100)
        c.set('b', 2, now=100)
        # set c at 111, 'a' should be expired
        c.set('c', 3, now=111)
        self.assertEqual(len(c), 1)
        self.assertEqual(c.get('c', now=111), 3)

    def test_service(self):
        service.reset()
        loader_calls = 0
        def loader(k):
            nonlocal loader_calls
            loader_calls += 1
            return f"val_{k}"
        
        self.assertEqual(service.lookup('a', loader), 'val_a')
        self.assertEqual(loader_calls, 1)
        self.assertEqual(service.lookup('a', loader), 'val_a')
        self.assertEqual(loader_calls, 1)
        self.assertEqual(service.stats(), {'hits': 1, 'misses': 1})
        
        service.reset()
        self.assertEqual(service.stats(), {'hits': 0, 'misses': 0})

if __name__ == '__main__':
    unittest.main()
