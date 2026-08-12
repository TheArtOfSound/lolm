import sys
import csv
import json
import argparse

class CustomArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        sys.exit(2)

def main():
    parser = CustomArgumentParser()
    parser.add_argument("--column")
    parser.add_argument("--precision", default="4")

    # This handles unknown arguments and missing required arguments
    args, unknown = parser.parse_known_args()
    if unknown:
        sys.exit(2)
    
    if not args.column:
        sys.stderr.write("Error: --column is required.\n")
        sys.exit(2)

    try:
        precision = int(args.precision)
    except ValueError:
        sys.stderr.write("Error: --precision must be an integer.\n")
        sys.exit(2)

    reader = csv.DictReader(sys.stdin)
    
    # DictReader will set fieldnames from the first row if not provided
    if reader.fieldnames is None:
        sys.stderr.write("Error: CSV has no header row.\n")
        sys.exit(3)

    if args.column not in reader.fieldnames:
        sys.stderr.write(f"Error: Column '{args.column}' not in header.\n")
        sys.exit(3)

    values = []
    for row in reader:
        val = row.get(args.column)
        if val is not None and val.strip() != "":
            try:
                values.append(float(val))
            except ValueError:
                sys.stderr.write(f"Error: Value '{val}' is not a number.\n")
                sys.exit(4)
    
    if not values:
        sys.stderr.write("Error: Column has no usable values.\n")
        sys.exit(5)

    count = len(values)
    min_val = min(values)
    max_val = max(values)
    sum_val = sum(values)
    mean_val = round(sum_val / count, precision)

    result = {
        "count": count,
        "min": min_val,
        "max": max_val,
        "mean": mean_val,
        "sum": sum_val
    }
    # Standard float formatting in JSON might be tricky, but python's json.dumps handles it.
    print(json.dumps(result))

if __name__ == "__main__":
    main()
