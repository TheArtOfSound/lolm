import sys
import re
from collections import Counter

def main():
    n = 10
    args = sys.argv[1:]
    file_path = None
    
    i = 0
    while i < len(args):
        if args[i] == '-n':
            i += 1
            if i >= len(args):
                print("Error: -n requires an argument", file=sys.stderr)
                sys.exit(2)
            try:
                n = int(args[i])
            except ValueError:
                print("Error: N must be an integer", file=sys.stderr)
                sys.exit(2)
        elif args[i].startswith('-'):
            print(f"Error: Unrecognised argument {args[i]}", file=sys.stderr)
            sys.exit(2)
        else:
            if file_path is not None:
                print("Error: Multiple files specified", file=sys.stderr)
                sys.exit(2)
            file_path = args[i]
        i += 1
        
    if file_path is None:
        print("Error: Missing FILE argument", file=sys.stderr)
        sys.exit(2)
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read().lower()
    except Exception as e:
        print(f"Error: Could not read file: {e}", file=sys.stderr)
        sys.exit(2)
        
    # Maximal run of a-z, 0-9, and '
    # Word boundaries are anything else
    # Apostrophes stripped from start and end
    
    # Matches sequences of allowed chars
    raw_words = re.findall(r"[a-z0-9']+", text)
    
    words = []
    for raw in raw_words:
        cleaned = raw.strip("'")
        if cleaned:
            words.append(cleaned)
            
    counts = Counter(words)
    
    # Sort by count descending, then alphabetically
    sorted_words = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    
    for word, count in sorted_words[:n]:
        print(f"{word}\t{count}")

if __name__ == '__main__':
    main()
