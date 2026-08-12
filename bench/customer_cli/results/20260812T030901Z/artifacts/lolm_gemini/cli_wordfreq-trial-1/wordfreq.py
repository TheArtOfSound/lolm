import sys
import re

def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Error: Missing FILE argument\n")
        sys.exit(2)
        
    n_val = 10
    file_path = None
    
    args = sys.argv[1:]
    idx = 0
    while idx < len(args):
        if args[idx] == "-n":
            if idx + 1 >= len(args):
                sys.stderr.write("Error: Missing value for -n\n")
                sys.exit(2)
            try:
                n_val = int(args[idx+1])
                idx += 2
            except ValueError:
                sys.stderr.write("Error: Non-integer N\n")
                sys.exit(2)
        elif args[idx].startswith("-"):
            sys.stderr.write(f"Error: Unrecognised argument {args[idx]}\n")
            sys.exit(2)
        else:
            if file_path is not None:
                sys.stderr.write("Error: Too many arguments\n")
                sys.exit(2)
            file_path = args[idx]
            idx += 1
    
    if file_path is None:
        sys.stderr.write("Error: Missing FILE argument\n")
        sys.exit(2)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().lower()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        sys.stderr.write(f"Error: Could not read file '{file_path}'\n")
        sys.exit(2)
    except Exception:
        sys.stderr.write("Error: Could not read file\n")
        sys.exit(2)

    # Word definition: maximal run of a-z, 0-9, and '
    # Strip ' from start/end
    # Discard empty
    
    # re.findall(r"[a-z0-9']+", content) finds words, 
    # but the requirement says 'after lowercasing',
    # and 'apostrophes stripped from the start and end of each word'.
    # A maximal run of [a-z0-9'] can have apostrophes inside.
    # The stripping only applies at the edges.
    
    # Corrected logic to match: "A word is a maximal run of the characters a-z, 0-9, and apostrophe"
    # then "apostrophes stripped from the start and end of each word and empty results discarded"
    
    # The maximal run is the sequence of [a-z0-9']
    
    words = re.findall(r"[a-z0-9']+", content)
    
    from collections import Counter
    counts = Counter()
    for w in words:
        stripped = w.strip("'")
        if stripped:
            counts[stripped] += 1
            
    # Sort by descending count, then alphabetically
    # The problem asks for descending count, then alphabetically for ties
    sorted_words = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    
    for word, count in sorted_words[:n_val]:
        sys.stdout.write(f"{word}\t{count}\n")

if __name__ == "__main__":
    main()
