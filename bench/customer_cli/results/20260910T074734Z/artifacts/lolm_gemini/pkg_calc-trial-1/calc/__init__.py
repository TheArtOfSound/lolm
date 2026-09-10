from .ops import add, sub, mul, div
import re

def evaluate(expression):
    # Simple recursive descent parser
    # Added whitespace handling to remove all spaces
    tokens = re.findall(r'\d+\.?\d*|\+|\-|\*|\/|\(|\)', expression.replace(' ', ''))
    
    pos = 0
    def peek(): return tokens[pos] if pos < len(tokens) else None
    def consume(): nonlocal pos; pos += 1; return tokens[pos-1]

    def factor():
        token = consume()
        if token == '+': return factor()
        if token == '-': return -factor()
        if token == '(':
            val = expression_parser()
            if consume() != ')': raise ValueError("Malformed expression: missing )")
            return val
        try:
            return float(token) if '.' in token else int(token)
        except:
            raise ValueError("Malformed expression: invalid token " + token)

    def term():
        val = factor()
        while peek() in ('*', '/'):
            op = consume()
            right = factor()
            if op == '*': val = val * right
            else: val = div(val, right)
        return val

    def expression_parser():
        val = term()
        while peek() in ('+', '-'):
            op = consume()
            right = term()
            if op == '+': val = add(val, right)
            else: val = sub(val, right)
        return val
    
    if not tokens: raise ValueError("Malformed expression: empty")
    result = expression_parser()
    if pos < len(tokens): raise ValueError("Malformed expression: extra tokens")
    
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result
