from solution import get

def test():
    # Basic
    data = {"a": {"b": 1}}
    assert get(data, "a.b") == 1
    assert get(data, "a.c") is None
    assert get(data, "a.c", default=42) == 42
    
    # List
    data = {"items": [{"name": "first"}, {"name": "second"}]}
    assert get(data, "items[0].name") == "first"
    assert get(data, "items[1].name") == "second"
    assert get(data, "items[2].name", "none") == "none"
    
    # Nested lists
    data = {"x": [[10, 20], [30, 40]]}
    assert get(data, "x[0][1]") == 20
    assert get(data, "x[1][0]") == 30
    assert get(data, "x[1][2]", "err") == "err"
    
    # Negative indices
    data = {"l": [1, 2, 3]}
    assert get(data, "l[-1]") == 3
    assert get(data, "l[-3]") == 1
    
    # Malformed paths
    try:
        get({}, "")
    except ValueError:
        pass
    else:
        raise AssertionError("Failed to raise ValueError for empty path")

    for p in ["a..b", ".a", "a.", "a[x]"]:
        try:
            get({}, p)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Failed to raise ValueError for {p}")

    print("All tests passed!")

if __name__ == "__main__":
    test()
