"""Split a command line into arguments."""


def split_args(line):
    args = []
    current_arg = []
    in_single_quote = False
    in_double_quote = False
    escaped = False
    started_arg = False

    i = 0
    while i < len(line):
        char = line[i]

        if escaped:
            current_arg.append(char)
            escaped = False
            started_arg = True
        elif char == "\\":
            if in_single_quote:
                current_arg.append(char)
                started_arg = True
            else:
                escaped = True
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            started_arg = True
        elif char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            started_arg = True
        elif char.isspace() and not in_single_quote and not in_double_quote:
            if started_arg:
                args.append("".join(current_arg))
                current_arg = []
                started_arg = False
        else:
            current_arg.append(char)
            started_arg = True
        i += 1

    if escaped or in_single_quote or in_double_quote:
        raise ValueError("Unbalanced quotes or trailing backslash")

    if started_arg:
        args.append("".join(current_arg))

    return args
