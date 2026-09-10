import re

def get(obj, path, default=None):
    if not path:
        raise ValueError("Malformed path: empty")
    
    if '..' in path or path.startswith('.') or path.endswith('.'):
        raise ValueError("Malformed path")

    if re.search(r'\[[^0-9\-]', path):
        raise ValueError("Malformed path")

    normalized = path.replace('[', '.[').replace('..', '.')
    parts = normalized.split('.')
    parts = [p for p in parts if p]
    
    curr = obj
    for part in parts:
        if part.startswith('['):
            if not part.endswith(']'):
                raise ValueError("Malformed path")
            
            content = part[1:-1]
            try:
                idx = int(content)
            except ValueError:
                raise ValueError("Malformed path")
                
            if isinstance(curr, (list, tuple)):
                if idx < 0:
                    idx = len(curr) + idx
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return default
            else:
                return default
        else:
            if not re.match(r'^[a-zA-Z0-9_]+$', part):
                raise ValueError("Malformed path")
            
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return default
                
    return curr
