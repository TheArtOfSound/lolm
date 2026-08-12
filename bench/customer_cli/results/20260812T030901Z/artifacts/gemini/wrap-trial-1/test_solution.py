from solution import wrap

def test_wrap():
    # Test basic wrapping
    text = "Hello world this is a test"
    assert wrap(text, 5) == ["Hello", "world", "this", "is a", "test"]
    
    # Test hard breaking
    text = "abcdefghij"
    assert wrap(text, 3) == ["abc", "def", "ghi", "j"]
    
    # Test paragraph preservation
    text = "Hello\n\nWorld"
    assert wrap(text, 10) == ["Hello", "", "World"]
    
    # Test empty text
    assert wrap("", 5) == []
    
    # Test width 1
    text = "a bc"
    assert wrap(text, 1) == ["a", "b", "c"]
    
    # Test ValueError
    try:
        wrap("text", 0)
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError"
    
    print("All tests passed!")

if __name__ == "__main__":
    test_wrap()
