import unittest
from solution import merge

class TestMergeIntervals(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(merge([]), [])

    def test_simple_merge(self):
        self.assertEqual(merge([[1, 3], [2, 6], [8, 10], [15, 18]]), [[1, 6], [8, 10], [15, 18]])

    def test_touching_intervals(self):
        self.assertEqual(merge([[1, 2], [2, 3]]), [[1, 3]])

    def test_nested_intervals(self):
        self.assertEqual(merge([[1, 4], [2, 3]]), [[1, 4]])

    def test_unordered_intervals(self):
        self.assertEqual(merge([[8, 10], [1, 3], [2, 6], [15, 18]]), [[1, 6], [8, 10], [15, 18]])

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            merge([[3, 1]])

    def test_no_mutation(self):
        intervals = [[2, 6], [1, 3]]
        original = list(intervals)
        merge(intervals)
        self.assertEqual(intervals, original)

if __name__ == '__main__':
    unittest.main()
