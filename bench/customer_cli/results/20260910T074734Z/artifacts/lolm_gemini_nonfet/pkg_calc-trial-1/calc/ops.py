def add(a, b): 
    res = a + b
    return res

def sub(a, b): 
    res = a - b
    return res

def mul(a, b): 
    res = a * b
    return res

def div(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b
