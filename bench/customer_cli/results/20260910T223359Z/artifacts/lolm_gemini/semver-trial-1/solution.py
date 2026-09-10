import re

def compare(a: str, b: str) -> int:
    """
    Compares two semantic version strings.
    Returns:
        -1 if a < b
        0 if a == b
        1 if a > b
    """
    semver_pattern = re.compile(r'^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$')

    def parse(version: str):
        match = semver_pattern.match(version)
        if not match:
            raise ValueError(f"Invalid semver: {version}")
        
        groups = match.groupdict()
        major = int(groups['major'])
        minor = int(groups['minor'])
        patch = int(groups['patch'])
        
        prerelease = groups['prerelease']
        if prerelease:
            pre_parts = prerelease.split('.')
            parsed_pre = []
            for part in pre_parts:
                if part.isdigit():
                    parsed_pre.append((0, int(part)))
                else:
                    parsed_pre.append((1, part))
        else:
            parsed_pre = None
            
        return (major, minor, patch), parsed_pre

    v1, pre1 = parse(a)
    v2, pre2 = parse(b)

    # 1. Compare numeric version
    if v1 < v2:
        return -1
    elif v1 > v2:
        return 1

    # 2. Compare prerelease
    # A version with a prerelease is lower than the same version without one.
    if pre1 is None and pre2 is not None:
        return 1
    if pre1 is not None and pre2 is None:
        return -1
    if pre1 is None and pre2 is None:
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
