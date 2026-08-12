def merge(base, override, list_strategy='replace'):
    """
    Deep merges two configuration dictionaries and returns a new one 
    without mutating either input.
    """
    def _merge(b, o, path=""):
        # A value of None on either side is always replaceable
        if b is None:
            return o
        if o is None:
            return b

        if isinstance(b, dict) and isinstance(o, dict):
            new_dict = b.copy()
            for key, value in o.items():
                # Correctly build path for nested dictionaries
                new_path = f"{path}.{key}" if path else str(key)
                if key in new_dict:
                    new_dict[key] = _merge(new_dict[key], value, new_path)
                else:
                    new_dict[key] = value
            return new_dict

        if isinstance(b, list) and isinstance(o, list):
            if list_strategy == 'replace':
                return o
            elif list_strategy == 'append':
                return b + o
            elif list_strategy == 'unique':
                seen = set()
                res = []
                for item in b + o:
                    if item not in seen:
                        res.append(item)
                        seen.add(item)
                return res
            else:
                raise ValueError(f"Unknown list_strategy: {list_strategy}")

        # Number handling (int/float)
        # Check if both are numbers (int or float) and NOT boolean
        is_b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
        is_o_num = isinstance(o, (int, float)) and not isinstance(o, bool)
        
        if is_b_num and is_o_num:
            return o

        # Type check: Any other type conflict raises a ValueError 
        # whose message contains the dotted path to the conflict.
        if type(b) is not type(o):
            raise ValueError(f"Type conflict at '{path}': {type(b).__name__} vs {type(o).__name__}")

        return o

    return _merge(base, override)
