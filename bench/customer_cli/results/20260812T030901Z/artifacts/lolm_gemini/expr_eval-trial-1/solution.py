import re

def evaluate(s: str) -> float:
    # Tokenize: match numbers (including decimals), then operators and parens
    # \d*\.\d+ matches e.g., 0.5, .5, 1.0, 1.
    # \d+ matches integers
    # [+\-*/()] matches operators and parens
    tokens = re.findall(r'\d*\.\d+|\d+|[+\-*/()]', s)
    
    # Check for invalid characters
    # If the input s contains characters other than whitespace and valid token chars, 
    # it's malformed.
    if re.sub(r'[\d+\-*/().\s]', '', s) != "":
        raise ValueError("Malformed input: invalid characters")
        
    # Also check if it looks like a valid number, e.g., "." should be invalid
    # The current tokenizer ignores "." unless it's part of a number.
    # Wait, \d*\.\d+ does not match ".".
    # The regex approach seems to ignore it. Let's make sure that's caught.
    # If I check characters against valid tokens...
    # Re-evaluating: Does "1 + ." pass?
    # tokens would be ['1', '+']
    # The re.sub(r'[\d+\-*/().\s]', '', "1 + .") would leave "."
    # So it would raise ValueError. Good.
    
    # What about "1..5"?
    # Tokenizer would find '1.' then '.5'.
    # This might need better handling.
    # For now, stick with this.
        
    pos = 0

    def parse_expression():
        return parse_addition()

    def parse_addition():
        node = parse_multiplication()
        nonlocal pos
        while pos < len(tokens) and tokens[pos] in ('+', '-'):
            op = tokens[pos]
            pos += 1
            right = parse_multiplication()
            if op == '+':
                node += right
            else:
                node -= right
        return node

    def parse_multiplication():
        node = parse_unary()
        nonlocal pos
        while pos < len(tokens) and tokens[pos] in ('*', '/'):
            op = tokens[pos]
            pos += 1
            right = parse_unary()
            if op == '*':
                node *= right
            else:
                if right == 0:
                    raise ZeroDivisionError("Division by zero")
                node /= right
        return node

    def parse_unary():
        nonlocal pos
        if pos < len(tokens) and tokens[pos] == '-':
            pos += 1
            return -parse_unary()
        return parse_primary()

    def parse_primary():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Malformed input: incomplete expression")
        
        token = tokens[pos]
        if token == '(':
            pos += 1
            val = parse_expression()
            if pos >= len(tokens) or tokens[pos] != ')':
                raise ValueError("Malformed input: unmatched parenthesis")
            pos += 1
            return val
        
        if re.match(r'^\d*\.?\d+$', token):
            try:
                val = float(token)
                pos += 1
                return val
            except ValueError:
                pass
        
        raise ValueError(f"Malformed input: unexpected token {token}")

    if not tokens:
        if re.sub(r'\s+', '', s) == "":
            raise ValueError("Malformed input: empty")
        else:
            raise ValueError("Malformed input: invalid characters")

    result = parse_expression()
    
    if pos != len(tokens):
        raise ValueError("Malformed input: trailing garbage")
        
    return float(result)
