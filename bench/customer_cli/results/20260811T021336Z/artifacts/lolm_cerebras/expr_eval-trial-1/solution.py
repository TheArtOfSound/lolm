"""Solution module providing evaluate(s) -> float.

Implements a simple arithmetic expression evaluator supporting:
- binary operators: +, -, *, /
- unary minus (e.g., -3, -(2+1))
- integer and decimal literals (e.g., 42, 3.14)
- parentheses for grouping
- arbitrary whitespace

Standard operator precedence and left associativity are observed.
Division by zero raises ZeroDivisionError.
Malformed input raises ValueError.

No use of eval/exec or external libraries.
"""

import re
from typing import List, Tuple, Union

Token = Tuple[str, str]  # (type, value)

# Token types
NUMBER = "NUMBER"
PLUS = "PLUS"
MINUS = "MINUS"
MUL = "MUL"
DIV = "DIV"
LPAREN = "LPAREN"
RPAREN = "RPAREN"
EOF = "EOF"

TOKEN_SPECIFICATION = [
    (NUMBER,  r"\d+(?:\.\d*)?|\.\d+"),  # integer or decimal, e.g., 12, 3.14, .5
    (PLUS,    r"\+"),
    (MINUS,   r"-"),
    (MUL,     r"\*"),
    (DIV,     r"/"),
    (LPAREN,  r"\("),
    (RPAREN,  r"\)"),
    ("SKIP", r"[ \t\r\n]+"),  # whitespace
    ("MISMATCH", r"."),  # any other character
]

TOK_REGEX = re.compile("|".join(f"(?P<{typ}>{pattern})" for typ, pattern in TOKEN_SPECIFICATION))


def tokenize(text: str) -> List[Token]:
    """Convert the input string into a list of tokens.

    Raises ValueError if an illegal character is encountered.
    """
    tokens: List[Token] = []
    for mo in TOK_REGEX.finditer(text):
        kind = mo.lastgroup
        value = mo.group()
        if kind == "SKIP":
            continue
        elif kind == "MISMATCH":
            raise ValueError(f"Unexpected character: {value!r}")
        elif kind == NUMBER:
            tokens.append((NUMBER, value))
        elif kind == PLUS:
            tokens.append((PLUS, value))
        elif kind == MINUS:
            tokens.append((MINUS, value))
        elif kind == MUL:
            tokens.append((MUL, value))
        elif kind == DIV:
            tokens.append((DIV, value))
        elif kind == LPAREN:
            tokens.append((LPAREN, value))
        elif kind == RPAREN:
            tokens.append((RPAREN, value))
        else:
            # Should never reach here
            raise ValueError(f"Unknown token kind: {kind}")
    tokens.append((EOF, ""))
    return tokens


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.current = tokens[0]

    def advance(self) -> None:
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current = self.tokens[self.pos]
        else:
            self.current = (EOF, "")

    def eat(self, token_type: str) -> None:
        if self.current[0] == token_type:
            self.advance()
        else:
            raise ValueError(f"Expected token {token_type}, got {self.current[0]}")

    def parse(self) -> float:
        if self.current[0] == EOF:
            raise ValueError("Empty expression")
        result = self.expr()
        if self.current[0] != EOF:
            raise ValueError("Unexpected trailing characters")
        return result

    # Grammar rules ---------------------------------------------------
    # expr   : term ((PLUS|MINUS) term)*
    def expr(self) -> float:
        result = self.term()
        while self.current[0] in (PLUS, MINUS):
            op = self.current[0]
            self.advance()
            right = self.term()
            if op == PLUS:
                result = result + right
            else:
                result = result - right
        return result

    # term   : factor ((MUL|DIV) factor)*
    def term(self) -> float:
        result = self.factor()
        while self.current[0] in (MUL, DIV):
            op = self.current[0]
            self.advance()
            right = self.factor()
            if op == MUL:
                result = result * right
            else:
                if right == 0:
                    raise ZeroDivisionError("division by zero")
                result = result / right
        return result

    # factor : (PLUS|MINUS) factor | primary
    def factor(self) -> float:
        if self.current[0] == PLUS:
            self.advance()
            return self.factor()
        if self.current[0] == MINUS:
            self.advance()
            return -self.factor()
        return self.primary()

    # primary: NUMBER | LPAREN expr RPAREN
    def primary(self) -> float:
        if self.current[0] == NUMBER:
            value = float(self.current[1])
            self.advance()
            return value
        if self.current[0] == LPAREN:
            self.advance()
            value = self.expr()
            if self.current[0] != RPAREN:
                raise ValueError("Missing closing parenthesis")
            self.advance()
            return value
        raise ValueError(f"Unexpected token: {self.current[0]}")


def evaluate(s: str) -> float:
    """Evaluate an arithmetic expression given as a string.

    Parameters
    ----------
    s: str
        Expression to evaluate.

    Returns
    -------
    float
        Result of the evaluation.

    Raises
    ------
    ValueError
        If the expression is malformed.
    ZeroDivisionError
        If a division by zero occurs.
    """
    tokens = tokenize(s)
    parser = Parser(tokens)
    return parser.parse()

# Simple sanity check when run as a script
if __name__ == "__main__":
    import sys
    expr = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        print(evaluate(expr))
    except Exception as e:
        print(type(e).__name__ + ": " + str(e))
