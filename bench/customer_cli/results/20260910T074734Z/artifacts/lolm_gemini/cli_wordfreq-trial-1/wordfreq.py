import sys
import re
from collections import Counter

def main():
    args = sys.argv[1:]
    n = 10
    file_path = None
    
    i = 0
    while i < len(args):
        if args[i] == '-n':
            if i + 1 >= len(args):
                sys.stderr.write("Error: -n requires an integer argument\n")
                sys.exit(2)
            try:
                n = int(args[i + 1])
            except ValueError:
                sys.stderr.write("Error: N must be an integer\n")
                sys.exit(2)
            i += 2
        elif args[i].startswith('-'):
            sys.stderr.write(f"Error: unrecognized argument {args[i]}\n")
            sys.exit(2)
        else:
            if file_path is not None:
                # Based on requirement "any unrecognised argument" - 
                # if there are already two arguments (program and maybe -n) 
                # and then a file, another positional argument is unrecognised.
                sys.stderr.write(f"Error: unrecognized argument {args[i]}\n")
                sys.exit(2)
            file_path = args[i]
            i += 1
            
    if file_path is None:
        sys.stderr.write("Error: missing FILE argument\n")
        sys.exit(2)
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read().lower()
    except Exception as e:
        sys.stderr.write(f"Error: could not read file: {e}\n")
        sys.exit(2)
        
    # Maximal run of a-z, 0-9, and apostrophe
    pattern = re.compile(r"[a-z0-9']+")
    raw_words = pattern.findall(text)
    
    words = []
    for w in raw_words:
        stripped = w.strip("'")
        if stripped:
            words.append(stripped)
            
    counts = Counter(words)
    
    # Sort by descending count, then alphabetically
    sorted_words = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    
    for i in range(min(n, len(sorted_words))):
        word, count = sorted_words[i]
        sys.stdout.write(f"{word}\t{count}\n")

if __name__ == '__main__':
    main()
