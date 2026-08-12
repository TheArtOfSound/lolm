import lexer
import runner

def test():
    # Test split_args
    assert lexer.split_args('a b c') == ['a', 'b', 'c']
    assert lexer.split_args('  a   b  ') == ['a', 'b']
    assert lexer.split_args('x"y"z') == ['xyz']
    assert lexer.split_args('""') == ['']
    assert lexer.split_args('a"b c"d') == ['ab cd']
    assert lexer.split_args(r'a\"b') == ['a"b']
    assert lexer.split_args(r'a\\b') == ['a\\b']
    assert lexer.split_args("'a b c'") == ['a b c']
    assert lexer.split_args("'a\"b'") == ['a"b']

    try:
        lexer.split_args("'abc")
        assert False
    except ValueError:
        pass
    
    try:
        lexer.split_args("a\\")
        assert False
    except ValueError:
        pass

    # Test parse_command
    assert runner.parse_command("ls -l") == {"program": "ls", "args": ["-l"]}
    
    try:
        runner.parse_command("   ")
        assert False
    except ValueError:
        pass

    print("All tests passed!")

if __name__ == "__main__":
    test()
