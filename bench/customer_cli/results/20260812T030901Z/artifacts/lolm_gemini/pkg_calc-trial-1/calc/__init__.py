import re
from .ops import add, sub, mul, div

def evaluate(expression):
    # This is a basic recursive descent parser for arithmetic expressions
    tokens = re.findall(r'\d+\.?\d*|\+|\-|\*|\/|\(|\)', expression)
    pos = 0

    def parse_expression():
        nonlocal pos
        node = parse_term()
        while pos < len(tokens) and tokens[pos] in ('+', '-'):
            op = tokens[pos]
            pos += 1
            right = parse_term()
            if op == '+': node = add(node, right)
            else: node = sub(node, right)
        return node

    def parse_term():
        nonlocal pos
        node = parse_factor()
        while pos < len(tokens) and tokens[pos] in ('*', '/'):
            op = tokens[pos]
            pos += 1
            right = parse_factor()
            if op == '*': node = mul(node, right)
            else: node = div(node, right)
        return node

    def parse_factor():
        nonlocal pos
        if pos >= len(tokens): raise ValueError("Malformed expression")
        token = tokens[pos]
        if token == '+':
            pos += 1
            return parse_factor()
        if token == '-':
            pos += 1
            return -parse_factor()
        if token == '(':
            pos += 1
            node = parse_expression()
            if pos >= len(tokens) or tokens[pos] != ')': raise ValueError("Malformed expression")
            pos += 1
            return node
        
        # Number literal
        try:
            pos += 1
            if '.' in token:
                return float(token)
            else:
                return int(token)
        except ValueError:
            raise ValueError("Malformed expression")

    result = parse_expression()
    if pos != len(tokens):
        raise ValueError("Malformed expression")
    
    # Convert to int if it's effectively an integer
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result
