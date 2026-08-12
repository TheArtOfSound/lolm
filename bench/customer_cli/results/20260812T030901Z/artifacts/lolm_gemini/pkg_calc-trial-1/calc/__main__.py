import sys
from . import evaluate

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 -m calc <expression>", file=sys.stderr)
        sys.exit(2)
    
    try:
        result = evaluate(sys.argv[1])
        print(result)
    except (ValueError, ZeroDivisionError) as e:
        print(e, file=sys.stderr)
        sys.exit(3)
    except Exception:
        # Catch unexpected errors to ensure exit 3
        print("Error evaluating expression", file=sys.stderr)
        sys.exit(3)

if __name__ == "__main__":
    main()
