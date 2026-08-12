from solution import evaluate

def test():
    # Basic
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("-1 + 2") == 1.0
    assert evaluate("10 / 2 / 2") == 2.5
    assert evaluate("1.5 * 2") == 3.0
    assert evaluate("  1 +  ( 2 * 3 )  ") == 7.0
    assert evaluate("1 + 2 * -3") == -5.0
    assert evaluate("-(-1)") == 1.0

    # Malformed (should raise ValueError)
    def assert_raises(expr):
        try:
            evaluate(expr)
            assert False, f"Expected ValueError for: {expr}"
        except ValueError:
            pass
        except Exception as e:
            assert False, f"Expected ValueError for {expr}, but got {type(e).__name__}: {e}"

    assert_raises("1 +")
    assert_raises("(1")
    assert_raises("")
    assert_raises("2 ** 3")
    assert_raises("1 + a")
    assert_raises("1 + )")
    assert_raises("1 + (2 * 3")
    
    # Division by zero (should raise ZeroDivisionError)
    try:
        evaluate("1 / 0")
        assert False
    except ZeroDivisionError:
        pass
    except Exception as e:
        assert False, f"Expected ZeroDivisionError, but got {type(e).__name__}: {e}"

    print("All tests passed!")

if __name__ == "__main__":
    test()
