from solution import evaluate

def test_basic():
    assert evaluate("1 + 2") == 3
    assert evaluate("1 - 2") == -1
    assert evaluate("2 * 3") == 6
    assert evaluate("6 / 2") == 3
    assert evaluate("1 + 2 * 3") == 7
    assert evaluate("(1 + 2) * 3") == 9

def test_unary():
    assert evaluate("-1 + 2") == 1
    assert evaluate("-1 * -2") == 2
    assert evaluate("-(1 + 2)") == -3

def test_decimals():
    assert evaluate("1.5 + 2.5") == 4.0
    assert evaluate("1.5 * 2") == 3.0

def test_whitespace():
    assert evaluate(" 1 + 2 ") == 3
    assert evaluate(" 1+2 * 3 ") == 7

def test_errors():
    try:
        evaluate("1 +")
        assert False, "Should have raised ValueError for 1 +"
    except ValueError:
        pass
    
    try:
        evaluate("(1")
        assert False, "Should have raised ValueError for (1"
    except ValueError:
        pass
        
    try:
        evaluate("")
        assert False, "Should have raised ValueError for empty"
    except ValueError:
        pass

    try:
        evaluate("2 ** 3")
        assert False, "Should have raised ValueError for 2 ** 3"
    except ValueError:
        pass

    try:
        evaluate("1 / 0")
        assert False, "Should have raised ZeroDivisionError for 1/0"
    except ZeroDivisionError:
        pass

if __name__ == "__main__":
    test_basic()
    test_unary()
    test_decimals()
    test_whitespace()
    test_errors()
    print("All tests passed")
