import re

def get(obj, path, default=None):
    if not path:
        raise ValueError("Malformed path: empty")
    
    # Check for empty steps in dotted paths
    if '..' in path or path.startswith('.') or path.endswith('.'):
        raise ValueError("Malformed path: empty segments")

    # Split path by dots
    segments = path.split('.')
    
    current = obj
    
    for segment in segments:
        # Check for bracket notation
        if '[' in segment:
            # Check for malformed bracket patterns like 'a[x]' (non-numeric index)
            parts = re.split(r'(\[.*?\])', segment)
            for part in parts:
                if not part:
                    continue
                if part.startswith('['):
                    inner = part[1:-1]
                    if not inner.lstrip('-').isdigit():
                        raise ValueError(f"Malformed path: invalid index '{inner}'")
                    
                    index = int(inner)
                    try:
                        if isinstance(current, (list, tuple)):
                            current = current[index]
                        else:
                            return default
                    except (IndexError, TypeError):
                        return default
                else:
                    # It's a key part
                    if isinstance(current, dict):
                        if part in current:
                            current = current[part]
                        else:
                            return default
                    else:
                        return default
        else:
            # Simple key access
            if isinstance(current, dict):
                if segment in current:
                    current = current[segment]
                else:
                    return default
            else:
                return default
                
    return current
