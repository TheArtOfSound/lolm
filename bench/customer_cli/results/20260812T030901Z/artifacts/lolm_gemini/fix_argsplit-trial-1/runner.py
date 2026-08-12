"""Turn a command line into a program plus arguments."""
from lexer import split_args


def parse_command(line):
    if not line or line.isspace():
        raise ValueError("Empty or whitespace-only command line")
    parts = split_args(line)
    return {"program": parts[0], "args": parts[1:]}
