"""ISO-8601 duration parser.

Provides ``parse_duration(s)`` which returns the total number of seconds as a float.
Supported components:
- Date part: years (Y), months (M), weeks (W), days (D)
  * Years are treated as 365 days, months as 30 days.
- Time part after ``T``: hours (H), minutes (M), seconds (S)
- Fractional values are allowed (e.g., ``PT0.5S``).
- A leading ``-`` negates the entire duration.

Invalid inputs raise ``ValueError``.
"""

import re

# Seconds per unit constants
_SECONDS_PER_YEAR = 365 * 24 * 3600
_SECONDS_PER_MONTH = 30 * 24 * 3600
_SECONDS_PER_WEEK = 7 * 24 * 3600
_SECONDS_PER_DAY = 24 * 3600
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_MINUTE = 60

# Regular expression based on ISO‑8601 duration grammar.
_DURATION_RE = re.compile(
    r"^(?P<sign>-)?P"
    r"(?:(?P<years>\d+(?:\.\d+)?)Y)?"
    r"(?:(?P<months>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<weeks>\d+(?:\.\d+)?)W)?"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?"
    r"$"
)


def _to_float(value: str | None) -> float:
    """Convert the captured string to float, defaulting to 0.0 if None."""
    return float(value) if value is not None else 0.0


def parse_duration(s: str) -> float:
    """Parse an ISO‑8601 duration string and return the total seconds.

    Parameters
    ----------
    s: str
        The ISO‑8601 duration, e.g. ``"P3DT4H5M6S"``.

    Returns
    -------
    float
        Total seconds represented by the duration.

    Raises
    ------
    ValueError
        If *s* is not a valid ISO‑8601 duration.
    """
    if not isinstance(s, str):
        raise ValueError("Duration must be a string")

    match = _duration_re.match(s)
    if not match:
        raise ValueError(f"Invalid ISO‑8601 duration: {s!r}")

    # Ensure at least one component is present (all groups would be None otherwise)
    if not any(match.group(name) for name in (
        "years", "months", "weeks", "days",
        "hours", "minutes", "seconds")):
        raise ValueError(f"Invalid ISO‑8601 duration (empty): {s!r}")

    sign = -1 if match.group('sign') else 1

    years = _to_float(match.group('years'))
    months = _to_float(match.group('months'))
    weeks = _to_float(match.group('weeks'))
    days = _to_float(match.group('days'))
    hours = _to_float(match.group('hours'))
    minutes = _to_float(match.group('minutes'))
    seconds = _to_float(match.group('seconds'))

    total_seconds = (
        years * _SECONDS_PER_YEAR +
        months * _SECONDS_PER_MONTH +
        weeks * _SECONDS_PER_WEEK +
        days * _SECONDS_PER_DAY +
        hours * _SECONDS_PER_HOUR +
        minutes * _SECONDS_PER_MINUTE +
        seconds
    )

    return sign * total_seconds

# Simple sanity check when run as a script (not executed during import)
if __name__ == "__main__":
    test_cases = {
        "P3DT4H5M6S": 3 * 86400 + 4 * 3600 + 5 * 60 + 6,
        "PT0.5S": 0.5,
        "P1Y": 365 * 86400,
        "-PT5M": -5 * 60,
        "PT1H": 3600,
    }
    for iso, expected in test_cases.items():
        result = parse_duration(iso)
        print(iso, result, expected, "OK" if abs(result - expected) < 1e-9 else "FAIL")
