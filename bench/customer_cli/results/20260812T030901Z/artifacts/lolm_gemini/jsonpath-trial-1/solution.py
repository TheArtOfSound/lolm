import re

def get(obj, path, default=None):
    if not path:
        raise ValueError("Malformed path: path cannot be empty.")
    
    if ".." in path or path.startswith(".") or path.endswith("."):
        raise ValueError("Malformed path: invalid sequence.")
    
    # Split path by '.' and brackets
    # Tokens can be:
    # 1. key (no dots, no brackets)
    # 2. key[idx1][idx2]...
    
    parts = []
    
    raw_parts = path.split('.')
    for p in raw_parts:
        if not p:
            raise ValueError("Malformed path: empty segment.")
        
        # Now handle brackets
        # e.g., 'items[0]' or 'x[1][2]'
        match = re.match(r'^([^\[]+)?(\[.*\])?$', p)
        if not match:
             raise ValueError(f"Malformed path: unexpected format {p}")
        
        key = match.group(1)
        brackets = match.group(2)
        
        if key:
            parts.append(key)
        
        if brackets:
            # find all [idx]
            # Use a regex that ensures no other characters are inside the brackets
            # except digits and minus sign
            bracket_tokens = re.findall(r'(\[-?\d+\])', brackets)
            
            # verify that everything in 'brackets' was matched
            # if we just joined them, it should match the original brackets
            if "".join(bracket_tokens) != brackets:
                # This could be because of malformed index like [a] or [1.2]
                raise ValueError(f"Malformed path: invalid bracket syntax {brackets}")
                
            for b in bracket_tokens:
                parts.append(b)
        
    current = obj
    
    for part in parts:
        if part.startswith('['):
            # Array index
            try:
                idx = int(part[1:-1])
                if not isinstance(current, (list, tuple)):
                    return default
                if idx < 0:
                    idx = len(current) + idx
                if idx < 0 or idx >= len(current):
                    return default
                current = current[idx]
            except (ValueError, IndexError, TypeError):
                return default
        else:
            # Dictionary key
            if not isinstance(current, dict):
                return default
            if part not in current:
                return default
            current = current[part]
            
    return current
