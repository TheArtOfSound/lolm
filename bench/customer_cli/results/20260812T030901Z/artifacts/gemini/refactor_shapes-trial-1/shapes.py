"""Area and perimeter for a few shapes."""
import math

_REGISTRY = {}

def register(kind, area_fn, perimeter_fn):
    _REGISTRY[kind] = (area_fn, perimeter_fn)

def kinds():
    return sorted(_REGISTRY.keys())

def area(shape):
    kind = shape["kind"]
    if kind not in _REGISTRY:
        raise ValueError(f"unknown shape: {kind}")
    return _REGISTRY[kind][0](shape)

def perimeter(shape):
    kind = shape["kind"]
    if kind not in _REGISTRY:
        raise ValueError(f"unknown shape: {kind}")
    return _REGISTRY[kind][1](shape)

# Register existing shapes
register("circle", 
         lambda s: math.pi * s["r"] ** 2, 
         lambda s: 2 * math.pi * s["r"])

register("rect", 
         lambda s: s["w"] * s["h"], 
         lambda s: 2 * (s["w"] + s["h"]))

register("square", 
         lambda s: s["side"] ** 2, 
         lambda s: 4 * s["side"])

# Register triangle
def _triangle_area(s):
    a, b, c = s["a"], s["b"], s["c"]
    # Triangle inequality check
    if a + b <= c or a + c <= b or b + c <= a:
        raise ValueError("invalid triangle sides")
    p = (a + b + c) / 2
    val = p * (p - a) * (p - b) * (p - c)
    if val <= 0:
        raise ValueError("invalid triangle sides")
    return math.sqrt(val)

def _triangle_perimeter(s):
    return s["a"] + s["b"] + s["c"]

register("triangle", _triangle_area, _triangle_perimeter)
