"""Minimal CSV reader (we cannot use the stdlib csv module here)."""

def parse(text):
    if not text:
        return []
    
    # Handle the case where the input ends with a newline, which should not produce an extra row
    if text.endswith('\n'):
        text = text[:-1]
    
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
                    # Doubled quote
                    current_field.append('"')
                    i += 1
                else:
                    # Closing quote
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
    
    # Add last row
    current_row.append("".join(current_field))
    rows.append(current_row)
    
    return rows
