from calc import evaluate
assert evaluate("1+2*3") == 7
assert evaluate("10/2") == 5.0
assert isinstance(evaluate("10/2"), float)
assert evaluate("1+2") == 3
assert isinstance(evaluate("1+2"), int)
assert evaluate("5.5*2") == 11.0
assert isinstance(evaluate("5.5*2"), float)
try:
    evaluate("1/0")
    assert False
except ZeroDivisionError:
    pass
try:
    evaluate("1+")
    assert False
except (ValueError, IndexError):
    pass
print("Tests passed")
