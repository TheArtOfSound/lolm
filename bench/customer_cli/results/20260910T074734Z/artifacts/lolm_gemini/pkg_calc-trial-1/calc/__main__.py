import sys
from calc import evaluate

def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: python3 -m calc <expression>\n")
        sys.exit(2)
    
    try:
        result = evaluate(sys.argv[1])
        print(result)
        sys.exit(0)
    except ZeroDivisionError as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(3)
    except Exception as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(3)

if __name__ == "__main__":
    main()
