"""ISO‑8601 duration parsing to total seconds.

Provides :func:`parse_duration` which accepts a string such as ``"P3DT4H5M6S"``
and returns the total duration in seconds as a ``float``.

Supported components:

* Date part (preceded by ``P``):
    * Years (``Y``) – interpreted as 365 days
    * Months (``M``) – interpreted as 30 days
    * Weeks (``W``) – 7 days
    * Days (``D``)
* Time part (after ``T``):
    * Hours (``H``)
    * Minutes (``M``)
    * Seconds (``S``) – may contain a fractional part
* An optional leading ``-`` makes the whole duration negative.

Any string that does not conform to the ISO‑8601 duration grammar described
above raises :class:`ValueError`.
"""

import re
from typing import Final

# Conversion constants (seconds per unit)
SECONDS_PER_YEAR: Final = 365 * 24 * 3600
SECONDS_PER_MONTH: Final = 30 * 24 * 3600
SECONDS_PER_WEEK: Final = 7 * 24 * 3600
SECONDS_PER_DAY: Final = 24 * 3600
SECONDS_PER_HOUR: Final = 3600
SECONDS_PER_MINUTE: Final = 60

# Regular expression that captures each component.  ``M`` appears twice –
# once in the date part (months) and once in the time part (minutes).  The
# regex therefore uses distinct named groups for each position.
_DURATION_RE = re.compile(
    r"^"
    r"(?P<sign>-)?"                     # optional leading minus
    r"P"                                # required "P" designator
    r"(?:(?P<years>\d+(?:\.\d+)?)Y)?"   # years
    r"(?:(?P<months>\d+(?:\.\d+)?)M)?"  # months (date part)
    r"(?:(?P<weeks>\d+(?:\.\d+)?)W)?"   # weeks
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"    # days
    r"(?:T"                             # time part follows 'T'
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"   # hours
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?" # minutes (time part)
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?" # seconds
    r")?"                               # time part optional
    r"$"
)


def parse_duration(s: str) -> float:
    """Parse an ISO‑8601 duration string and return total seconds.

    Parameters
    ----------
    s: str
        The duration string to parse.

    Returns
    -------
    float
        Total duration in seconds.

    Raises
    ------
    ValueError
        If *s* is not a valid ISO‑8601 duration according to the supported
        subset.
    """
    if not isinstance(s, str) or not s:
        raise ValueError("Duration must be a non‑empty string")

    match = _DURATION_RE.fullmatch(s)
    if not match:
        raise ValueError(f"Invalid ISO‑8601 duration: {s!r}")

    # Ensure that at least one component is present – the regex would also
    # match a bare 'P' which is not allowed.
    if not any(match.group(name) for name in (
        "years", "months", "weeks", "days",
        "hours", "minutes", "seconds")):
        raise ValueError(f"Invalid ISO‑8601 duration (no components): {s!r}")

    # Helper to convert a possibly‑None string to a float, defaulting to 0.
    def _to_float(text: str | None) -> float:
        return float(text) if text is not None else 0.0

    years = _to_float(match.group("years"))
    months = _to_float(match.group("months"))
    weeks = _to_float(match.group("weeks"))
    days = _to_float(match.group("days"))
    hours = _to_float(match.group("hours"))
    minutes = _to_float(match.group("minutes"))
    seconds = _to_float(match.group("seconds"))

    total_seconds = (
        years * SECONDS_PER_YEAR +
        months * SECONDS_PER_MONTH +
        weeks * SECONDS_PER_WEEK +
        days * SECONDS_PER_DAY +
        hours * SECONDS_PER_HOUR +
        minutes * SECONDS_PER_MINUTE +
        seconds
    )

    if match.group("sign"):
        total_seconds = -total_seconds

    return float(total_seconds)

# Simple sanity check when run directly (not part of the required API).
if __name__ == "__main__":
    # Example usages; they will raise if something is wrong.
    examples = [
        "P3DT4H5M6S",
        "PT0.5S",
        "P1Y",
        "-PT5M",
        "PT1H",
    ]
    for ex in examples:
        print(ex, "=>", parse_duration(ex))
