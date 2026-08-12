def split_args(line):
    args = []
    current = []
    i = 0
    in_double = False
    in_single = False
    escaped = False
    has_part = False

    while i < len(line):
        char = line[i]
        if escaped:
            current.append(char)
            escaped = False
            has_part = True
        elif in_double:
            if char == '\\':
                if i + 1 < len(line) and line[i+1] in ('"', '\\'):
                    i += 1
                    current.append(line[i])
                    has_part = True
                else:
                    raise ValueError("Trailing lone backslash or invalid escape in double quotes")
            elif char == '"':
                in_double = False
            else:
                current.append(char)
                has_part = True
        elif in_single:
            if char == "'":
                in_single = False
            else:
                current.append(char)
                has_part = True
        elif char == '\\':
            escaped = True
            if i + 1 == len(line):
                raise ValueError("Trailing lone backslash")
        elif char == '"':
            in_double = True
            has_part = True
        elif char == "'":
            in_single = True
            has_part = True
        elif char.isspace():
            if has_part:
                args.append("".join(current))
                current = []
                has_part = False
        else:
            current.append(char)
            has_part = True
        i += 1

    if escaped or in_double or in_single:
        raise ValueError("Unbalanced quote or trailing backslash")
    if has_part:
        args.append("".join(current))
    return args
