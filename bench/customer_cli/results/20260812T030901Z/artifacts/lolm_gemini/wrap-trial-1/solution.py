def wrap(text: str, width: int) -> list[str]:
    if width < 1:
        raise ValueError("width must be at least 1")
    if not text:
        return []

    lines = []
    # Preserve blank lines (paragraphs)
    paragraphs = text.split('\n')
    
    for para in paragraphs:
        if not para:
            lines.append("")
            continue
            
        words = para.split()
        if not words:
            # This handles lines that contain only whitespace
            lines.append("")
            continue
            
        current_line = []
        current_length = 0
        
        for word in words:
            # Handle words longer than width
            if len(word) > width:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = []
                    current_length = 0
                
                # Hard break the word
                for i in range(0, len(word), width):
                    lines.append(word[i:i+width])
                continue

            # Check if word fits in current line
            # If current_line exists, we need one space + word
            if current_line:
                if current_length + 1 + len(word) <= width:
                    current_line.append(word)
                    current_length += 1 + len(word)
                else:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    current_length = len(word)
            else:
                current_line.append(word)
                current_length = len(word)
        
        if current_line:
            lines.append(" ".join(current_line))
            
    return lines
