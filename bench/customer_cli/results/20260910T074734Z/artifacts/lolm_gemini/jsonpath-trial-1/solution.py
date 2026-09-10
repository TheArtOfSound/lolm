import re

def get(obj, path, default=None):
    if not path:
        raise ValueError("Malformed path: empty")
    if '..' in path or path.startswith('.') or path.endswith('.'):
        raise ValueError("Malformed path: invalid dots")

    parts = []
    i = 0
    while i < len(path):
        if path[i] == '.':
            i += 1
            continue
        
        if path[i] == '[':
            j = path.find(']', i)
            if j == -1:
                raise ValueError(f"Malformed path: unclosed bracket")
            index_str = path[i+1:j]
            if not index_str.lstrip('-').isdigit():
                raise ValueError(f"Malformed path: invalid index {index_str}")
            parts.append(int(index_str))
            i = j + 1
        else:
            match = re.match(r'[a-zA-Z0-9_]+', path[i:])
            if not match:
                raise ValueError(f"Malformed path: invalid character")
            part = match.group(0)
            parts.append(part)
            i += len(part)
            
            # Check if this identifier is immediately followed by another without dot/bracket
            # E.g., 'a[1]b' -> in my logic, 'a' then '[1]' then 'b'
            # If the original path was 'a[1]b', my loop would be:
            # i=0: identifier 'a', parts=['a'], i=1
            # i=1: bracket '[1]', parts=['a', 1], i=4
            # i=4: identifier 'b', parts=['a', 1, 'b'], i=5
            # This seems correct, it parses fine.
            
    curr = obj
    for part in parts:
        try:
            if isinstance(part, str):
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                else:
                    return default
            else: # int
                if isinstance(curr, (list, tuple)):
                    if part < 0:
                        part = len(curr) + part
                    if 0 <= part < len(curr):
                        curr = curr[part]
                    else:
                        return default
                else:
                    return default
        except (TypeError, KeyError, IndexError):
            return default
            
    return curr
