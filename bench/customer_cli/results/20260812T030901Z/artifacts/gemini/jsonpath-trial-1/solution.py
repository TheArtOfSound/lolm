import re

def get(obj, path, default=None):
    if not path:
        raise ValueError("Malformed path: empty")
    
    # Path validation: look for '..', start/end with '.', or [x] invalid inside
    if '..' in path or path.startswith('.') or path.endswith('.'):
        raise ValueError(f"Malformed path: {path}")

    # Split path by dots
    parts = path.split('.')
    current = obj
    
    for part in parts:
        # Check for list indexing [idx]
        if '[' in part:
            if not part.endswith(']'):
                raise ValueError(f"Malformed path: {part}")
            
            # Check for invalid syntax like 'a[x]'
            if not re.match(r'^[a-zA-Z0-9_]*(\[-?\d+\])+$', part):
                raise ValueError(f"Malformed path: {part}")
                
            bracket_split = re.split(r'\[', part)
            key = bracket_split[0]
            indices = bracket_split[1:]
            
            # Navigate to key first if it exists
            if key:
                if not isinstance(current, dict) or key not in current:
                    return default
                current = current[key]
            
            # Now navigate through the indices
            for index_part in indices:
                idx_str = index_part[:-1] # strip ']'
                idx = int(idx_str)
                
                if not isinstance(current, (list, tuple)):
                    return default
                
                try:
                    current = current[idx]
                except IndexError:
                    return default
        else:
            # Simple dict key
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
            
    return current
