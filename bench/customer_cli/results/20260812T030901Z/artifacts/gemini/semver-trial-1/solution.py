import re

def compare(a: str, b: str) -> int:
    def parse_version(v: str):
        # Ignore metadata
        v = v.split('+')[0]
        
        # Regex for semver: major.minor.patch[-prerelease]
        # Allow optional prerelease
        pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z\.-]+))?$'
        match = re.match(pattern, v)
        if not match:
            raise ValueError(f"Malformed semantic version: {v}")
            
        major, minor, patch, prerelease = match.groups()
        return [int(major), int(minor), int(patch)], prerelease

    v1_parts, v1_pre = parse_version(a)
    v2_parts, v2_pre = parse_version(b)

    # Compare major, minor, patch
    if v1_parts < v2_parts: return -1
    if v1_parts > v2_parts: return 1

    # Compare prerelease
    if v1_pre is None and v2_pre is None: return 0
    if v1_pre is None: return 1  # version without pre > version with pre
    if v2_pre is None: return -1
    
    # Both have prerelease
    pre1 = v1_pre.split('.')
    pre2 = v2_pre.split('.')
    
    for p1, p2 in zip(pre1, pre2):
        # Check if numeric
        is_n1, is_n2 = p1.isdigit(), p2.isdigit()
        if is_n1 and is_n2:
            n1, n2 = int(p1), int(p2)
            if n1 < n2: return -1
            if n1 > n2: return 1
        elif is_n1: return -1  # numeric < alphanumeric
        elif is_n2: return 1
        else:
            if p1 < p2: return -1
            if p1 > p2: return 1
            
    if len(pre1) < len(pre2): return -1
    if len(pre1) > len(pre2): return 1
    return 0
