import re

def compare(a: str, b: str) -> int:
    def parse(version: str):
        # Ignore metadata
        if '+' in version:
            version = version.split('+')[0]
        
        # Check for prerelease
        prerelease = None
        if '-' in version:
            version, prerelease = version.split('-', 1)
        
        # Validate main version
        parts = version.split('.')
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version}")
        try:
            major, minor, patch = map(int, parts)
        except ValueError:
            raise ValueError(f"Invalid version format: {version}")
        
        # Parse prerelease
        prerelease_parts = []
        if prerelease:
            for part in prerelease.split('.'):
                if part.isdigit():
                    prerelease_parts.append((0, int(part)))
                else:
                    prerelease_parts.append((1, part))
        
        return (major, minor, patch), prerelease_parts

    v1, pre1 = parse(a)
    v2, pre2 = parse(b)

    # Compare main version
    if v1 < v2:
        return -1
    if v1 > v2:
        return 1
    
    # Same version, compare prerelease
    # A version WITH a prerelease is lower than the same version WITHOUT one.
    if not pre1 and pre2:
        return 1
    if pre1 and not pre2:
        return -1
    if not pre1 and not pre2:
        return 0
    
    # Both have prerelease
    for p1, p2 in zip(pre1, pre2):
        if p1 < p2:
            return -1
        if p1 > p2:
            return 1
            
    if len(pre1) < len(pre2):
        return -1
    if len(pre1) > len(pre2):
        return 1
        
    return 0
