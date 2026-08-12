import re

def to_roman(n: int) -> str:
    if not isinstance(n, int) or not (1 <= n <= 3999):
        raise ValueError("Input must be an integer between 1 and 3999.")

    val = [
        (1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
        (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
        (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')
    ]
    res = []
    for i, roman in val:
        while n >= i:
            res.append(roman)
            n -= i
    return "".join(res)

def from_roman(s: str) -> int:
    if not isinstance(s, str) or not s:
        raise ValueError("Input must be a non-empty string.")
    
    # Regex for valid roman numerals
    # Standard: M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})
    # But for 1-3999, it must have at least one character.
    pattern = r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
    if not re.match(pattern, s) or s == "":
        raise ValueError("Invalid Roman numeral.")

    roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    res = 0
    prev_val = 0
    for char in reversed(s):
        curr_val = roman_map[char]
        if curr_val < prev_val:
            res -= curr_val
        else:
            res += curr_val
        prev_val = curr_val
    return res
