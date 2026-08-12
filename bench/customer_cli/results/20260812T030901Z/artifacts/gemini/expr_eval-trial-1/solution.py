import re

def evaluate(s: str) -> float:
    """
    Evaluates an arithmetic expression string with support for:
    +, -, *, /, unary minus, parentheses, and arbitrary whitespace.
    """
    if not s or not s.strip():
        raise ValueError("Empty expression")

    tokens = re.findall(r'\d*\.\d+|\d+|[+\-*/()]', s)
    # Validate tokens against allowed characters
    if any(c not in '0123456789.+-*/() ' for c in s):
        raise ValueError("Invalid character in expression")

    pos = 0

    def parse_expression():
        nonlocal pos
        node = parse_term()
        while pos < len(tokens) and tokens[pos] in ('+', '-'):
            op = tokens[pos]
            pos += 1
            right = parse_term()
            if op == '+':
                node += right
            else:
                node -= right
        return node

    def parse_term():
        nonlocal pos
        node = parse_factor()
        while pos < len(tokens) and tokens[pos] in ('*', '/'):
            op = tokens[pos]
            pos += 1
            right = parse_factor()
            if op == '*':
                node *= right
            else:
                if right == 0:
                    raise ZeroDivisionError("Division by zero")
                node /= right
        return node

    def parse_factor():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Unexpected end of expression")
        
        token = tokens[pos]
        
        if token == '-':
            pos += 1
            return -parse_factor()
        
        if token == '(':
            pos += 1
            val = parse_expression()
            if pos >= len(tokens) or tokens[pos] != ')':
                raise ValueError("Missing closing parenthesis")
            pos += 1
            return val
        
        pos += 1
        try:
            return float(token)
        except ValueError:
            raise ValueError(f"Invalid token: {token}")

    result = parse_expression()
    if pos < len(tokens):
        raise ValueError("Extra tokens at end of expression")
    return result
