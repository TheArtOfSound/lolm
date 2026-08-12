import math

_REGISTRY = {}

def register(kind, area_fn, perimeter_fn):
    _REGISTRY[kind] = (area_fn, perimeter_fn)

def kinds():
    return sorted(_REGISTRY.keys())

def area(shape):
    kind = shape.get("kind")
    if kind not in _REGISTRY:
        raise ValueError(f"unknown shape: {kind}")
    return _REGISTRY[kind][0](shape)

def perimeter(shape):
    kind = shape.get("kind")
    if kind not in _REGISTRY:
        raise ValueError(f"unknown shape: {kind}")
    return _REGISTRY[kind][1](shape)

# Register default shapes
register("circle", 
         lambda s: math.pi * s["r"] ** 2, 
         lambda s: 2 * math.pi * s["r"])

register("rect", 
         lambda s: s["w"] * s["h"], 
         lambda s: 2 * (s["w"] + s["h"]))

register("square", 
         lambda s: s["side"] ** 2, 
         lambda s: 4 * s["side"])

def _triangle_area(s):
    a, b, c = s["a"], s["b"], s["c"]
    # Check triangle inequality and positive sides
    if a + b <= c or a + c <= b or b + c <= a or a <= 0 or b <= 0 or c <= 0:
        raise ValueError("sides do not form a valid triangle")
    s_semi = (a + b + c) / 2
    return math.sqrt(s_semi * (s_semi - a) * (s_semi - b) * (s_semi - c))

register("triangle",
         _triangle_area,
         lambda s: s["a"] + s["b"] + s["c"])
