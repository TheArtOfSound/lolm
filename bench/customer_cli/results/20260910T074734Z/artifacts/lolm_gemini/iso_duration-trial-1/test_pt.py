from solution import parse_duration

try:
    print(parse_duration('PT'))
except ValueError:
    print("Caught 'PT'")
