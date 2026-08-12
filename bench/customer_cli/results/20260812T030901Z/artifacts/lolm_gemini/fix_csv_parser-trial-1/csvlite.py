def parse(text):
    """Parses CSV text into a list of rows."""
    if not text:
        return []
    
    # We must treat the whole text, including potential final newline.
    # The requirement is that a trailing newline must not produce an extra row.
    
    rows = []
    current_row = []
    current_field = []
    in_quotes = False
    
    i = 0
    while i < len(text):
        char = text[i]
        
        if in_quotes:
            if char == '"':
                if i + 1 < len(text) and text[i+1] == '"':
                    current_field.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                current_field.append(char)
        else:
            if char == '"':
                in_quotes = True
            elif char == ',':
                current_row.append("".join(current_field))
                current_field = []
            elif char == '\n':
                current_row.append("".join(current_field))
                rows.append(current_row)
                current_row = []
                current_field = []
            else:
                current_field.append(char)
        i += 1
    
    # After the loop, if we have content in current_row or current_field, add it as the final row.
    # If the text ended in a newline, current_row and current_field will be empty here,
    # which is exactly what we want to avoid the extra row.
    if current_row or current_field:
        current_row.append("".join(current_field))
        rows.append(current_row)
    
    return rows
