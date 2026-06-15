# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Automatic versioning for the daily release agent.

  canary:  x.y.z-canary.YYYYMMDD.RUN   (every daily run that ships something)
  patch:   x.y.(z+1)                   (default stable bump)
  minor:   x.(y+1).0                   (new public feature)
  major:   (x+1).0.0                   (breaking API change — must be justified)

Pure string math + a tiny package.json reader/writer; no network, no npm needed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Tuple

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def parse(version: str) -> Tuple[int, int, int]:
    m = _SEMVER.match((version or "").strip())
    if not m:
        raise ValueError(f"not a semver: {version!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump_patch(version: str) -> str:
    x, y, z = parse(version)
    return f"{x}.{y}.{z + 1}"


def bump_minor(version: str) -> str:
    x, y, _ = parse(version)
    return f"{x}.{y + 1}.0"


def bump_major(version: str) -> str:
    x, _, _ = parse(version)
    return f"{x + 1}.0.0"


def canary_version(base: str, date: str, run: int | str) -> str:
    """`x.y.z-canary.YYYYMMDD.run` — date as YYYY-MM-DD or YYYYMMDD."""
    x, y, z = parse(base)
    d = (date or "").replace("-", "")[:8]
    return f"{x}.{y}.{z}-canary.{d}.{run}"


def read_pkg_version(pkg_path: str | Path) -> str:
    return json.loads(Path(pkg_path).read_text()).get("version", "0.0.0")


def write_pkg_version(pkg_path: str | Path, version: str) -> None:
    p = Path(pkg_path)
    data = json.loads(p.read_text())
    data["version"] = version
    p.write_text(json.dumps(data, indent=2) + "\n")
