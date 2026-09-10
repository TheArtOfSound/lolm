import re

def compare(a: str, b: str) -> int:
    """
    Compares two semantic version strings.
    Returns:
        -1 if a < b
         0 if a == b
         1 if a > b
    Raises ValueError if either version is invalid.
    """
    pattern = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$')

    def parse(version: str):
        match = pattern.match(version)
        if not match:
            raise ValueError(f"Invalid version format: {version}")
        
        major, minor, patch, prerelease, metadata = match.groups()
        return (int(major), int(minor), int(patch)), prerelease

    ver_a, pre_a = parse(a)
    ver_b, pre_b = parse(b)

    # Compare numeric version (major, minor, patch)
    if ver_a < ver_b: return -1
    if ver_a > ver_b: return 1

    # If numeric versions are equal, compare prerelease
    # A version WITH a prerelease is lower than the same version WITHOUT one.
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is None:
        return 1
    if pre_b is None:
        return -1

    # Both have prereleases
    parts_a = pre_a.split('.')
    parts_b = pre_b.split('.')

    for p_a, p_b in zip(parts_a, parts_b):
        # Numeric identifiers have lower precedence than non-numeric
        a_is_digit = p_a.isdigit()
        b_is_digit = p_b.isdigit()

        if a_is_digit and b_is_digit:
            val_a, val_b = int(p_a), int(p_b)
            if val_a < val_b: return -1
            if val_a > val_b: return 1
        elif a_is_digit:
            return -1
        elif b_is_digit:
            return 1
        else:
            if p_a < p_b: return -1
            if p_a > p_b: return 1
    
    if len(parts_a) < len(parts_b): return -1
    if len(parts_a) > len(parts_b): return 1
    
    return 0

if __name__ == "__main__":
    pass
