import re

def parse_duration(s: str) -> float:
    if not s:
        raise ValueError("Empty string is not a valid duration")
    
    negative = False
    if s.startswith('-'):
        negative = True
        s = s[1:]
    
    if not s.startswith('P'):
        raise ValueError("Invalid duration format")
    
    if s == 'P':
        raise ValueError("Invalid duration format")
        
    s = s[1:] # remove P
    
    has_t = 'T' in s
    if has_t:
        parts = s.split('T')
        if len(parts) != 2:
            raise ValueError("Invalid duration format")
        date_part, time_part = parts
    else:
        date_part = s
        time_part = ''
        
    if not date_part and not time_part:
        raise ValueError("Invalid duration format")
        
    total_seconds = 0.0
    
    # Parse date part
    if date_part:
        # Y, M, W, D
        match = re.fullmatch(r'(?:(\d+(?:\.\d+)?)Y)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)W)?(?:(\d+(?:\.\d+)?)D)?', date_part)
        if not match or not any(match.groups()):
             raise ValueError("Invalid date component")
        
        y, m, w, d = match.groups()
        total_seconds += float(y or 0) * 365 * 24 * 3600
        total_seconds += float(m or 0) * 30 * 24 * 3600
        total_seconds += float(w or 0) * 7 * 24 * 3600
        total_seconds += float(d or 0) * 24 * 3600

    # Parse time part
    if time_part:
        match = re.fullmatch(r'(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?', time_part)
        if not match or not any(match.groups()):
             raise ValueError("Invalid time component")
        
        h, m, s_part = match.groups()
        total_seconds += float(h or 0) * 3600
        total_seconds += float(m or 0) * 60
        total_seconds += float(s_part or 0)

    return -total_seconds if negative else total_seconds
