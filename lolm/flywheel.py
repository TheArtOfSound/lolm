# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The autonomy flywheel — the agent earns its bars from verified outcomes.

Every completed run contributes one ``(measured_uncertainty, was_correct)`` pair
to a durable log. The calibrator and the selective-risk bars (lolm.autonomy /
lolm.calibration) are fit on that log, so the agent's autonomy is grounded in
its OWN verified track record and tightens as it runs — the compounding moat:
the more it does and gets checked, the more autonomy it mathematically deserves.

"was_correct" is the deterministic verifier + contract result from the receipt
(math_check / task_contract), never telemetry and never self-report. Runs with
no objective correctness signal are NOT recorded — a flywheel fed on vibes would
calibrate to vibes.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lolm.calibration import (
    SelectiveThreshold,
    UncertaintyCalibrator,
    selective_threshold,
)


class AutonomyFlywheel:
    """Durable (uncertainty, outcome) log + a calibrator fit on it.

    Thread-safe append; the calibrator is cached and refit every
    ``refit_every`` new records. Below ``min_fit`` records the calibrator is
    ``None`` and the gate falls back to its conservative prior — an agent with
    no track record does not get to claim calibrated autonomy.
    """

    def __init__(self, path: str | Path, min_fit: int = 20, refit_every: int = 10):
        self.path = Path(path)
        self.min_fit = min_fit
        self.refit_every = refit_every
        self._lock = threading.Lock()
        self._cal: Optional[UncertaintyCalibrator] = None
        self._n_at_fit = -1
        self._count = self._count_lines()

    def _count_lines(self) -> int:
        try:
            with self.path.open() as f:
                return sum(1 for _ in f)
        except FileNotFoundError:
            return 0

    def record(self, uncertainty: Optional[float], correct: Optional[bool],
               meta: Optional[Dict[str, Any]] = None) -> bool:
        """Append one verified outcome. No-ops (returns False) when either the
        uncertainty or the correctness label is missing — we never guess."""
        if uncertainty is None or correct is None:
            return False
        row: Dict[str, Any] = {"u": round(float(uncertainty), 4),
                               "y": 1 if correct else 0, "t": int(time.time())}
        if meta:
            row["m"] = meta
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._count += 1
        return True

    def _load(self) -> Tuple[List[float], List[int]]:
        us: List[float] = []
        ys: List[int] = []
        try:
            with self.path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "u" in r and "y" in r:
                        us.append(float(r["u"]))
                        ys.append(int(r["y"]))
        except FileNotFoundError:
            pass
        return us, ys

    def calibrator(self) -> Optional[UncertaintyCalibrator]:
        """Fit (or return cached) calibrator. None until ``min_fit`` records."""
        with self._lock:
            fresh = self._cal is not None and (self._count - self._n_at_fit) < self.refit_every
            if fresh:
                return self._cal
            us, ys = self._load()
            self._cal = UncertaintyCalibrator().fit(us, ys) if len(us) >= self.min_fit else None
            self._n_at_fit = self._count
            return self._cal

    def selective_bar(self, target_risk: float) -> SelectiveThreshold:
        """The largest uncertainty acceptable at ``target_risk`` on the log."""
        us, ys = self._load()
        return selective_threshold(us, ys, target_risk)

    @property
    def count(self) -> int:
        return self._count

    def stats(self) -> Dict[str, Any]:
        us, ys = self._load()
        n = len(ys)
        return {
            "n": n,
            "accuracy": round(sum(ys) / n, 4) if n else None,
            "calibrated": n >= self.min_fit,
            "mean_uncertainty": round(sum(us) / n, 4) if n else None,
        }
