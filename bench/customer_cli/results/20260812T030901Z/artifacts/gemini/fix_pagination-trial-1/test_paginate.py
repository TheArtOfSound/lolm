
import math
import unittest
from paginate import page_items, total_pages

class TestPagination(unittest.TestCase):
    def test_page_items(self):
        items = list(range(10))
        # page 1, 3 items -> [0, 1, 2]
        self.assertEqual(page_items(items, 1, 3), [0, 1, 2])
        # page 2, 3 items -> [3, 4, 5]
        self.assertEqual(page_items(items, 2, 3), [3, 4, 5])
        # page 4, 3 items -> [9]
        self.assertEqual(page_items(items, 4, 3), [9])
        # page 5, 3 items -> []
        self.assertEqual(page_items(items, 5, 3), [])
        
    def test_total_pages(self):
        self.assertEqual(total_pages(10, 3), 4)
        self.assertEqual(total_pages(9, 3), 3)
        self.assertEqual(total_pages(0, 3), 0)

    def test_validation(self):
        with self.assertRaises(ValueError):
            page_items([], 0, 3)
        with self.assertRaises(ValueError):
            page_items([], 1, 0)

if __name__ == '__main__':
    unittest.main()
