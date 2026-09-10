import re

def parse_duration(s: str) -> float:
    if not isinstance(s, str) or not s:
        raise ValueError("Invalid duration format")
    
    is_negative = False
    if s.startswith('-'):
        is_negative = True
        s = s[1:]
    
    if not s.startswith('P'):
        raise ValueError("Invalid duration format: must start with P")
    
    # After removing 'P', s could be empty
    remaining = s[1:]
    if not remaining:
        raise ValueError("Invalid duration format")
        
    date_part = ""
    time_part = ""
    
    if 'T' in remaining:
        parts = remaining.split('T', 1)
        date_part = parts[0]
        time_part = parts[1]
    else:
        date_part = remaining
        
    # Validation: if T was present, at least one of date or time parts must exist
    # If the input was 'PT', then date_part='', time_part='' -> Invalid
    if 'T' in remaining and not date_part and not time_part:
        raise ValueError("Invalid duration format")

    total_seconds = 0.0
    
    # Process date
    if date_part:
        date_match = re.findall(r'(\d+(?:\.\d+)?)([YMWD])', date_part)
        if not date_match:
            raise ValueError("Invalid date component")
        
        # Validate that the string only contains valid parts
        processed_len = sum(len(m[0]) + len(m[1]) for m in date_match)
        if processed_len != len(date_part):
            raise ValueError("Invalid characters in date part")
            
        for val, unit in date_match:
            val = float(val)
            if unit == 'Y':
                total_seconds += val * 365 * 24 * 3600
            elif unit == 'M':
                total_seconds += val * 30 * 24 * 3600
            elif unit == 'W':
                total_seconds += val * 7 * 24 * 3600
            elif unit == 'D':
                total_seconds += val * 24 * 3600
                
    # Process time
    if time_part:
        time_match = re.findall(r'(\d+(?:\.\d+)?)([HMS])', time_part)
        if not time_match:
            raise ValueError("Invalid time component")
            
        processed_len = sum(len(m[0]) + len(m[1]) for m in time_match)
        if processed_len != len(time_part):
            raise ValueError("Invalid characters in time part")
            
        for val, unit in time_match:
            val = float(val)
            if unit == 'H':
                total_seconds += val * 3600
            elif unit == 'M':
                total_seconds += val * 60
            elif unit == 'S':
                total_seconds += val
    elif 'T' in remaining and not time_part:
        # e.g., 'P1YT'
        raise ValueError("Invalid time component")

    return -total_seconds if is_negative else total_seconds
