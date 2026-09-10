import re

def parse_duration(s: str) -> float:
    if not isinstance(s, str) or not s:
        raise ValueError("Invalid duration format")

    original_s = s
    is_negative = False
    if s.startswith('-'):
        is_negative = True
        s = s[1:]
    
    if not s.startswith('P'):
        raise ValueError("Invalid duration format")
    
    s = s[1:]
    if not s:
        raise ValueError("Invalid duration format")

    # Split into date and time
    parts = s.split('T')
    if len(parts) > 2:
        raise ValueError("Invalid duration format")
    
    date_part = parts[0]
    time_part = parts[1] if len(parts) == 2 else ""

    if not date_part and not time_part:
        raise ValueError("Invalid duration format")
    
    # Check if 'T' was provided but no time part
    if len(parts) == 2 and not time_part:
        raise ValueError("Invalid duration format")

    total_seconds = 0.0

    # Parse date part
    if date_part:
        # Note: Valid ISO 8601 usually requires ordered units (Y, M, W, D).
        # The prompt implies Y=365 days, M=30 days, W=7 days, D=1 day.
        date_pattern = re.compile(r'(?P<val>\d+(?:\.\d+)?)(?P<unit>[YMWD])')
        matches = date_pattern.findall(date_part)
        if not matches:
            raise ValueError("Invalid duration format")
        
        # Verify that all characters in date_part were consumed
        consumed = "".join([m[0] + m[1] for m in matches])
        if consumed != date_part:
            raise ValueError("Invalid duration format")
        
        for val_str, unit in matches:
            val = float(val_str)
            if unit == 'Y':
                total_seconds += val * 365 * 24 * 3600
            elif unit == 'M':
                total_seconds += val * 30 * 24 * 3600
            elif unit == 'W':
                total_seconds += val * 7 * 24 * 3600
            elif unit == 'D':
                total_seconds += val * 24 * 3600
    
    # Parse time part
    if time_part:
        time_pattern = re.compile(r'(?P<val>\d+(?:\.\d+)?)(?P<unit>[HMS])')
        matches = time_pattern.findall(time_part)
        if not matches:
            raise ValueError("Invalid duration format")
        
        # Verify that all characters in time_part were consumed
        consumed = "".join([m[0] + m[1] for m in matches])
        if consumed != time_part:
            raise ValueError("Invalid duration format")
        
        for val_str, unit in matches:
            val = float(val_str)
            if unit == 'H':
                total_seconds += val * 3600
            elif unit == 'M':
                total_seconds += val * 60
            elif unit == 'S':
                total_seconds += val
    
    if is_negative:
        total_seconds = -total_seconds
        
    return float(total_seconds)
