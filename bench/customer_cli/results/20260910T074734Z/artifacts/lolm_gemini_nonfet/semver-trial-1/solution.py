import re

def compare(a: str, b: str) -> int:
    def parse_semver(version: str):
        if not version:
            raise ValueError("Empty version string")
        
        # Split build metadata
        if '+' in version:
            version, _ = version.split('+', 1)
        
        # Split prerelease
        prerelease = None
        if '-' in version:
            version, prerelease = version.split('-', 1)
        
        # Validate main version (major.minor.patch)
        parts = version.split('.')
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version}")
        
        try:
            major, minor, patch = map(int, parts)
        except ValueError:
            raise ValueError(f"Invalid version components: {version}")
            
        # Parse prerelease
        parsed_prerelease = []
        if prerelease:
            for part in prerelease.split('.'):
                if part.isdigit():
                    parsed_prerelease.append(int(part))
                else:
                    parsed_prerelease.append(part)
        
        return (major, minor, patch), parsed_prerelease

    ver1, pre1 = parse_semver(a)
    ver2, pre2 = parse_semver(b)
    
    # Compare main version
    if ver1 < ver2: return -1
    if ver1 > ver2: return 1
    
    # Compare prerelease
    # Versions with prerelease are lower than those without
    if pre1 and not pre2: return -1
    if not pre1 and pre2: return 1
    if not pre1 and not pre2: return 0
    
    # Both have prerelease, compare identifiers
    for p1, p2 in zip(pre1, pre2):
        if isinstance(p1, int) and isinstance(p2, int):
            if p1 < p2: return -1
            if p1 > p2: return 1
        elif isinstance(p1, int): # numeric < alphanumeric
            return -1
        elif isinstance(p2, int): # alphanumeric > numeric
            return 1
        else: # both alphanumeric
            if p1 < p2: return -1
            if p1 > p2: return 1
            
    # If all compared identifiers are equal, check length
    if len(pre1) < len(pre2): return -1
    if len(pre1) > len(pre2): return 1
    
    return 0
