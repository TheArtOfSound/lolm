import copy

def _resolve_pointer(doc, path):
    if not path:
        return doc, None, None
    if not path.startswith('/'):
        raise ValueError("Path must start with /")
    
    parts = path.lstrip('/').split('/')
    # Handle unescaping: ~1 -> /, ~0 -> ~
    # Special note: The JSON pointer spec says:
    # "The pointer path is a slash-separated list of tokens."
    # If the path is just "/", it results in [""] from split.
    # We should handle it properly.
    if path == '/':
        parts = ['']
    
    parts = [p.replace('~1', '/').replace('~0', '~') for p in parts]
    
    curr = doc
    parent = None
    last_key = None
    
    for i, part in enumerate(parts):
        parent = curr
        last_key = part
        
        if isinstance(curr, list):
            if part == '-':
                if i == len(parts) - 1:
                    return curr, parent, part
                else:
                    raise ValueError("Cannot traverse through '-'")
            try:
                idx = int(part)
            except ValueError:
                raise ValueError(f"Invalid array index: {part}")
            
            if idx < 0 or idx >= len(curr):
                raise ValueError(f"Index out of range: {idx}")
            curr = curr[idx]
        elif isinstance(curr, dict):
            if part not in curr:
                # For add, we might need to return the parent to add to it
                if i == len(parts) - 1:
                    return None, parent, part
                raise ValueError(f"Path not found: {part}")
            curr = curr[part]
        else:
            raise ValueError("Path points to a scalar")
            
    return curr, parent, last_key

def apply_patch(doc, ops):
    doc = copy.deepcopy(doc)
    
    for op in ops:
        if 'op' not in op or 'path' not in op:
            raise ValueError("Missing 'op' or 'path'")
        
        op_name = op['op']
        path = op['path']
        
        if op_name in ('add', 'replace', 'test'):
            if 'value' not in op:
                raise ValueError(f"Missing 'value' for {op_name}")
            value = op['value']
            
        if op_name == 'add':
            if path == '':
                doc = value
                continue
            
            # Use resolve for parent
            parts = path.lstrip('/').split('/')
            parts = [p.replace('~1', '/').replace('~0', '~') for p in parts]
            
            if len(parts) == 1 and parts[0] == '': # path was "/"
                parent = doc
                key = "" # not used really for root
            else:
                parent_path = '/' + '/'.join(parts[:-1]) if len(parts) > 1 else ''
                key = parts[-1]
                if parent_path == '':
                    parent = doc
                else:
                    _, parent, _ = _resolve_pointer(doc, parent_path)
            
            if isinstance(parent, list):
                if key == '-':
                    parent.append(value)
                else:
                    parent.insert(int(key), value)
            elif isinstance(parent, dict):
                parent[key] = value
            else:
                raise ValueError("Cannot add to non-container")
                
        elif op_name == 'remove':
            _, parent, key = _resolve_pointer(doc, path)
            if parent is None:
                raise ValueError("Cannot remove root")
            if isinstance(parent, list):
                parent.pop(int(key))
            else:
                del parent[key]
                
        elif op_name == 'replace':
            _, parent, key = _resolve_pointer(doc, path)
            if parent is None:
                doc = value
            elif isinstance(parent, list):
                parent[int(key)] = value
            else:
                parent[key] = value
                
        elif op_name == 'move':
            if 'from' not in op:
                raise ValueError("Missing 'from' for move")
            from_path = op['from']
            # Get value
            val, p_parent, p_key = _resolve_pointer(doc, from_path)
            # Remove
            if p_parent is None:
                raise ValueError("Cannot move root")
            if isinstance(p_parent, list):
                p_parent.pop(int(p_key))
            else:
                del p_parent[p_key]
            # Add
            _, t_parent, t_key = _resolve_pointer(doc, path)
            if isinstance(t_parent, list):
                if t_key == '-':
                    t_parent.append(val)
                else:
                    t_parent.insert(int(t_key), val)
            else:
                t_parent[t_key] = val
                
        elif op_name == 'copy':
            if 'from' not in op:
                raise ValueError("Missing 'from' for copy")
            val, _, _ = _resolve_pointer(doc, op['from'])
            # Add
            _, t_parent, t_key = _resolve_pointer(doc, path)
            if isinstance(t_parent, list):
                if t_key == '-':
                    t_parent.append(copy.deepcopy(val))
                else:
                    t_parent.insert(int(t_key), copy.deepcopy(val))
            else:
                t_parent[t_key] = copy.deepcopy(val)
                
        elif op_name == 'test':
            val, _, _ = _resolve_pointer(doc, path)
            if val != value:
                raise ValueError("Test failed")
        else:
            raise ValueError(f"Unsupported op: {op_name}")
            
    return doc
