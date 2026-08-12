from jsonpatch import apply_patch

def test():
    # Test basic
    doc = {"foo": "bar"}
    ops = [{"op": "replace", "path": "/foo", "value": "baz"}]
    assert apply_patch(doc, ops) == {"foo": "baz"}
    assert doc == {"foo": "bar"} # check immutability

    # Test add
    doc = {"a": 1}
    ops = [{"op": "add", "path": "/b", "value": 2}]
    assert apply_patch(doc, ops) == {"a": 1, "b": 2}
    
    # Test remove
    doc = {"a": 1, "b": 2}
    ops = [{"op": "remove", "path": "/a"}]
    assert apply_patch(doc, ops) == {"b": 2}
    
    # Test array append
    doc = [1, 2]
    ops = [{"op": "add", "path": "/-", "value": 3}]
    assert apply_patch(doc, ops) == [1, 2, 3]

    # Test escaping
    doc = {"a/b": 1, "c~d": 2}
    ops = [{"op": "test", "path": "/a~1b", "value": 1}, {"op": "test", "path": "/c~0d", "value": 2}]
    apply_patch(doc, ops)
    
    # Test move
    doc = {"a": 1, "b": 2}
    ops = [{"op": "move", "from": "/a", "path": "/b"}] # Invalid, would overwrite if not careful? 
    # Actually move /a to /c
    ops = [{"op": "move", "from": "/a", "path": "/c"}]
    assert apply_patch(doc, ops) == {"b": 2, "c": 1}

    print("All tests passed!")

if __name__ == "__main__":
    test()
