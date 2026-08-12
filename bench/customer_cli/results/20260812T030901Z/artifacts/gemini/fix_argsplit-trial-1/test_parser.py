import unittest
from lexer import split_args
from runner import parse_command

class TestCommandParsing(unittest.TestCase):
    def test_split_args(self):
        # Basic
        self.assertEqual(split_args("ls -l"), ["ls", "-l"])
        self.assertEqual(split_args("  ls   -l  "), ["ls", "-l"])
        
        # Quotes
        self.assertEqual(split_args('echo "hello world"'), ["echo", "hello world"])
        self.assertEqual(split_args("echo 'hello world'"), ["echo", "hello world"])
        self.assertEqual(split_args('x"y"z'), ["xyz"])
        self.assertEqual(split_args('""'), [""])
        
        # Escapes
        self.assertEqual(split_args(r'echo "he\"llo"'), ["echo", 'he"llo'])
        self.assertEqual(split_args(r'echo \\'), ["echo", "\\"])
        self.assertEqual(split_args(r"echo 'he\"llo'"), ["echo", r'he\"llo']) # Single quotes don't escape
        self.assertEqual(split_args(r'echo \a'), ["echo", "a"])
        
        # Errors
        with self.assertRaises(ValueError):
            split_args('"unbalanced')
        with self.assertRaises(ValueError):
            split_args('trailing\\')

    def test_parse_command(self):
        self.assertEqual(parse_command("ls -l"), {"program": "ls", "args": ["-l"]})
        with self.assertRaises(ValueError):
            parse_command("")
        with self.assertRaises(ValueError):
            parse_command("   ")

if __name__ == '__main__':
    unittest.main()
