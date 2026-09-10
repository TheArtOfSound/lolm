from solution import parse_duration

try:
    print(parse_duration(''))
except ValueError:
    print("Caught ''")

try:
    print(parse_duration('P'))
except ValueError:
    print("Caught 'P'")

try:
    print(parse_duration('hello'))
except ValueError:
    print("Caught 'hello'")

try:
    print(parse_duration('3D'))
except ValueError:
    print("Caught '3D'")
