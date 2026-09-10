import re
from .ops import add, sub, mul, div

def evaluate(expression):
    tokens = tokenize(expression)
    result = parse_expression(tokens)
    if tokens:
        raise ValueError("Malformed expression")
    
    # Return int if exact integer arithmetic (if possible, though this is tricky)
    # The requirement says: 
    # "returning an int when the arithmetic is exact integer arithmetic 
    # and a float when division or a decimal literal is involved."
    # The current approach might return float for division, which is correct.
    return result

def tokenize(expr):
    token_pattern = re.compile(r'\d+\.\d+|\d+|[+\-*/()]')
    return token_pattern.findall(expr.replace(" ", ""))

def parse_expression(tokens):
    node = parse_term(tokens)
    while tokens and tokens[0] in ('+', '-'):
        op = tokens.pop(0)
        right = parse_term(tokens)
        if op == '+':
            node = add(node, right)
        else:
            node = sub(node, right)
    return node

def parse_term(tokens):
    node = parse_factor(tokens)
    while tokens and tokens[0] in ('*', '/'):
        op = tokens.pop(0)
        right = parse_factor(tokens)
        if op == '*':
            node = mul(node, right)
        else:
            node = div(node, right)
    return node

def parse_factor(tokens):
    if not tokens:
        raise ValueError("Unexpected end of expression")
    
    token = tokens.pop(0)
    
    if token == '+':
        return parse_factor(tokens)
    if token == '-':
        return -parse_factor(tokens)
    if token == '(':
        node = parse_expression(tokens)
        if not tokens or tokens.pop(0) != ')':
            raise ValueError("Missing closing parenthesis")
        return node
    
    # number
    if '.' in token:
        return float(token)
    return int(token)
