import re

def parse_duration(s: str) -> float:
    """
    Converts an ISO-8601 duration string to total seconds.
    Supports Y (365 days), M (30 days), W (7 days), D, H, M, S (including fractional).
    """
    if not s or not s.startswith(('-', 'P')):
        raise ValueError("Invalid duration format")

    is_negative = False
    if s.startswith('-'):
        is_negative = True
        s = s[1:]
    
    if not s.startswith('P'):
        raise ValueError("Invalid duration format")
        
    s = s[1:] # remove P
    
    if not s:
        raise ValueError("Invalid duration format")
    
    # Check for time part
    date_part = ""
    time_part = ""
    
    if 'T' in s:
        date_part, time_part = s.split('T', 1)
    else:
        date_part = s
        
    if not date_part and not time_part:
        raise ValueError("Invalid duration format")

    total_seconds = 0.0
    
    # Parse date part
    if date_part:
        # Regex to match units
        date_units = re.findall(r'(\d+(?:\.\d+)?)([YMWD])', date_part)
        if not date_units and date_part:
             raise ValueError("Invalid duration format")
        
        for val, unit in date_units:
            val = float(val)
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
        time_units = re.findall(r'(\d+(?:\.\d+)?)([HMS])', time_part)
        if not time_units and time_part:
             raise ValueError("Invalid duration format")
             
        for val, unit in time_units:
            val = float(val)
            if unit == 'H':
                total_seconds += val * 3600
            elif unit == 'M':
                total_seconds += val * 60
            elif unit == 'S':
                total_seconds += val

    if is_negative:
        total_seconds = -total_seconds
        
    return float(total_seconds)
