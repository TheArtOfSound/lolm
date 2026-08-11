"""Utility to get a nested value from dicts/lists using a dotted path with bracket indices.

The function ``get`` safely traverses the object and returns a default value when the path cannot be
resolved. It raises ``ValueError`` only for malformed path strings.

Examples
--------
>>> data = {"a": {"b": 1}, "items": [{"name": "x"}], "x": [[0, 1], [2, 3]]}
>>> get(data, "a.b")
1
>>> get(data, "items[0].name")
'x'
>>> get(data, "x[1][0]")
2
>>> get(data, "missing", default='no')
'no'
>>> get(data, "items[2]", default=None) is None
True
"""

from __future__ import annotations
import re
from typing import Any

__all__ = ["get"]


def _parse_path(path: str) -> list[tuple[str, list[int]]]:
    """Parse a dotted path into a list of (name, [indices]) tuples.

    The function validates the path and raises ``ValueError`` for malformed strings.
    """
    if not path:
        raise ValueError("Path cannot be empty")
    if ".." in path:
        raise ValueError("Path contains consecutive dots")
    if path[0] == "." or path[-1] == ".":
        raise ValueError("Path cannot start or end with a dot")

    parts = path.split('.')
    result: list[tuple[str, list[int]]] = []
    index_pat = re.compile(r"\[(-?\d+)\]")
    name_pat = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    for part in parts:
        # extract the leading name
        m_name = name_pat.fullmatch(part)
        if m_name:
            # name without any brackets
            result.append((part, []))
            continue
        # name with possible brackets
        # match name at start
        m_start = name_pat.match(part)
        if not m_start:
            raise ValueError(f"Malformed segment '{part}' in path")
        name = m_start.group(0)
        rest = part[len(name):]
        indices: list[int] = []
        pos = 0
        while pos < len(rest):
            if rest[pos] != '[':
                raise ValueError(f"Unexpected character '{rest[pos]}' in segment '{part}'")
            # find closing bracket
            close = rest.find(']', pos)
            if close == -1:
                raise ValueError(f"Missing closing bracket in segment '{part}'")
            num_str = rest[pos + 1 : close]
            if not re.fullmatch(r"-?\d+", num_str):
                raise ValueError(f"Non‑integer index '{num_str}' in segment '{part}'")
            indices.append(int(num_str))
            pos = close + 1
        result.append((name, indices))
    return result


def get(obj: Any, path: str, default: Any = None) -> Any:
    """Retrieve a nested value from *obj* using *path*.

    Parameters
    ----------
    obj:
        The root object, typically a ``dict`` containing other ``dict``/``list`` values.
    path:
        Dotted path where each segment may contain optional ``[index]`` parts, e.g. ``"a.b"``
        or ``"items[0].name"``.
    default:
        Value returned when the path cannot be resolved.

    Returns
    -------
    Any
        The located value or *default* if any step fails.

    Raises
    ------
    ValueError
        If *path* is syntactically invalid.
    """
    try:
        steps = _parse_path(path)
    except ValueError:
        # re‑raise to keep the original semantics
        raise

    current = obj
    for name, indices in steps:
        # dict lookup
        if isinstance(current, dict):
            if name in current:
                current = current[name]
            else:
                return default
        else:
            return default
        # list/tuple indexing
        for idx in indices:
            if isinstance(current, (list, tuple)):
                try:
                    current = current[idx]
                except IndexError:
                    return default
            else:
                return default
    return current
