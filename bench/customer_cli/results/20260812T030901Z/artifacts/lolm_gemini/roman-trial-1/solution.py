import re

def to_roman(n: int) -> str:
    if not isinstance(n, int):
        raise ValueError("Input must be an integer")
    if not 1 <= n <= 3999:
        raise ValueError("Input must be between 1 and 3999")
    
    val = [
        1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1
    ]
    syb = [
        "M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"
    ]
    
    roman_num = ''
    i = 0
    while n > 0:
        for _ in range(n // val[i]):
            roman_num += syb[i]
            n -= val[i]
        i += 1
    return roman_num

def from_roman(s: str) -> int:
    if not isinstance(s, str) or not s:
        raise ValueError("Input must be a non-empty string")
    
    # Regex for standard Roman numerals
    # Thousands: M{0,3}
    # Hundreds: (CM|CD|D?C{0,3})
    # Tens: (XC|XL|L?X{0,3})
    # Ones: (IX|IV|V?I{0,3})
    pattern = r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
    
    # Check for empty string case explicitly because regex matches it
    if not s or not re.match(pattern, s):
        raise ValueError("Invalid Roman numeral")

    roman_map = {
        'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000
    }
    
    total = 0
    prev_value = 0
    for char in reversed(s):
        value = roman_map[char]
        if value < prev_value:
            total -= value
        else:
            total += value
        prev_value = value
    
    # Ensure it's in the valid range 1-3999
    if not 1 <= total <= 3999:
        raise ValueError("Invalid Roman numeral")
        
    return total
