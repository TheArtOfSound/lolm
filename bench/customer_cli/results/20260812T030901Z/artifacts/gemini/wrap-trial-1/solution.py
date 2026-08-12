def wrap(text: str, width: int) -> list[str]:
    if width < 1:
        raise ValueError("Width must be at least 1")
    if not text:
        return []

    lines = []
    paragraphs = text.split('\n')
    
    for i, paragraph in enumerate(paragraphs):
        if paragraph == "":
            lines.append("")
            continue
        
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
            
        current_line = []
        current_length = 0
        
        for word in words:
            if current_length == 0:
                # First word in line
                if len(word) > width:
                    # Hard break word
                    for j in range(0, len(word), width):
                        lines.append(word[j:j+width])
                else:
                    current_line.append(word)
                    current_length = len(word)
            else:
                # Check if word fits
                if current_length + 1 + len(word) <= width:
                    current_line.append(word)
                    current_length += 1 + len(word)
                else:
                    # Line full
                    lines.append(" ".join(current_line))
                    # Handle word
                    if len(word) > width:
                        # Hard break word
                        for j in range(0, len(word), width):
                            lines.append(word[j:j+width])
                        current_line = []
                        current_length = 0
                    else:
                        current_line = [word]
                        current_length = len(word)
        
        if current_line:
            lines.append(" ".join(current_line))
            
    return lines
