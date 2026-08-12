"""Run me with: python3 test_matrix.py"""
from matrix import Matrix

a = Matrix([[1, 2], [3, 4]])
b = Matrix([[5, 6], [7, 8]])
assert (a + b) == Matrix([[6, 8], [10, 12]])
assert (a * b) == Matrix([[19, 22], [43, 50]])
assert (a * 2) == Matrix([[2, 4], [6, 8]])
assert a.T == Matrix([[1, 3], [2, 4]])
assert a.shape == (2, 2)
assert Matrix.identity(2) == Matrix([[1, 0], [0, 1]])
print("OK")
