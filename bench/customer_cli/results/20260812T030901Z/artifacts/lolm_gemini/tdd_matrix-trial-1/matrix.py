class Matrix:
    def __init__(self, data):
        if not data or not all(isinstance(row, list) for row in data):
            raise ValueError("Invalid matrix data")
        rows = len(data)
        cols = len(data[0])
        if cols == 0:
            raise ValueError("Empty matrix")
        for row in data:
            if len(row) != cols:
                raise ValueError("Ragged rows")
        self._data = [row[:] for row in data]
        self._shape = (rows, cols)

    @property
    def shape(self):
        return self._shape

    @property
    def T(self):
        rows, cols = self._shape
        new_data = [[self._data[r][c] for r in range(rows)] for c in range(cols)]
        return Matrix(new_data)

    def __add__(self, other):
        if self._shape != other.shape:
            raise ValueError("Mismatched shapes")
        rows, cols = self._shape
        new_data = [[self._data[r][c] + other._data[r][c] for c in range(cols)] for r in range(rows)]
        return Matrix(new_data)

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            rows, cols = self._shape
            new_data = [[self._data[r][c] * other for c in range(cols)] for r in range(rows)]
            return Matrix(new_data)
        elif isinstance(other, Matrix):
            if self._shape[1] != other.shape[0]:
                raise ValueError("Inner dimensions disagree")
            rows, cols_self = self._shape
            _, cols_other = other.shape
            new_data = [[sum(self._data[r][k] * other._data[k][c] for k in range(cols_self)) 
                         for c in range(cols_other)] for r in range(rows)]
            return Matrix(new_data)
        return NotImplemented

    def __eq__(self, other):
        if not isinstance(other, Matrix):
            return False
        return self._data == other._data

    @staticmethod
    def identity(n):
        if n <= 0:
            raise ValueError("Invalid size")
        data = [[1 if r == c else 0 for c in range(n)] for r in range(n)]
        return Matrix(data)
