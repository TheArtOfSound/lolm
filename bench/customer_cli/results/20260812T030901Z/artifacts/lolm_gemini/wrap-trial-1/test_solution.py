from solution import wrap

def test_wrap():
    # Test case 1: Basic wrapping
    text = "hello world this is a test"
    assert wrap(text, 5) == ["hello", "world", "this", "is a", "test"]
    
    # Test case 2: Paragraphs
    text = "hello world\n\nthis is a test"
    assert wrap(text, 5) == ["hello", "world", "", "this", "is a", "test"]
    
    # Test case 3: Long words
    text = "longword"
    assert wrap(text, 4) == ["long", "word"]
    
    # Test case 4: Empty text
    assert wrap("", 5) == []
    
    # Test case 5: Width error
    try:
        wrap("test", 0)
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError"
        
    # Test case 6: Multiple spaces
    # split() without arguments handles multiple spaces by treating them as a single delimiter
    text = "a  b"
    assert wrap(text, 3) == ["a b"]
    
    # Test case 7: Trailing spaces check
    # Our implementation uses " ".join(), so it shouldn't produce trailing spaces.
    # Let's verify.
    result = wrap("a b", 5)
    for r in result:
        assert not r.endswith(" ")
        
    print("All tests passed!")

if __name__ == "__main__":
    test_wrap()
