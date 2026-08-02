# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Retrieval Bankruptcy Protocol.

After an empty result, an identical query/source pair is prohibited.
Another retrieval requires a transformed query and predicted information gain;
repeated zero gain forces clarification or abstention.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _qkey(query: str, source_scope: str = "") -> str:
    norm = " ".join((query or "").lower().split())
    raw = f"{norm}|{source_scope or '*'}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class RetrievalAttempt:
    query: str
    source_scope: str
    key: str
    hit_count: int
    predicted_gain: float
    actual_gain: float
    transformed_from: str = ""
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RetrievalBankruptcy:
    def __init__(self, max_zero_streak: int = 2) -> None:
        self.max_zero_streak = max_zero_streak
        self.attempts: List[RetrievalAttempt] = []
        self._zero_keys: Dict[str, int] = {}  # key -> consecutive zero results
        self.zero_streak = 0

    def may_retrieve(
        self,
        query: str,
        *,
        source_scope: str = "",
        predicted_gain: float = 0.0,
        transformed: bool = False,
    ) -> Tuple[bool, str]:
        key = _qkey(query, source_scope)
        zeros = self._zero_keys.get(key, 0)
        if zeros >= 1 and not transformed:
            return False, (
                f"identical zero-result retrieval blocked for query/source "
                f"(key={key}); transform the query and declare predicted gain"
            )
        if zeros >= 1 and predicted_gain <= 0:
            return False, (
                "retrieval after empty result requires predicted_information_gain > 0"
            )
        if self.zero_streak >= self.max_zero_streak and predicted_gain <= 0:
            return False, (
                f"{self.zero_streak} consecutive zero-gain retrievals — "
                "clarify with the user or abstain"
            )
        return True, "allowed"

    def record(
        self,
        query: str,
        *,
        source_scope: str = "",
        hit_count: int = 0,
        predicted_gain: float = 0.0,
        transformed_from: str = "",
    ) -> RetrievalAttempt:
        key = _qkey(query, source_scope)
        # Actual gain: positive if new hits
        actual = float(hit_count) if hit_count > 0 else 0.0
        att = RetrievalAttempt(
            query=query,
            source_scope=source_scope,
            key=key,
            hit_count=hit_count,
            predicted_gain=predicted_gain,
            actual_gain=actual,
            transformed_from=transformed_from,
            ts=time.time(),
        )
        self.attempts.append(att)
        if hit_count <= 0:
            self._zero_keys[key] = self._zero_keys.get(key, 0) + 1
            self.zero_streak += 1
        else:
            self._zero_keys[key] = 0
            self.zero_streak = 0
        return att

    def force_clarify(self) -> bool:
        return self.zero_streak >= self.max_zero_streak

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zero_streak": self.zero_streak,
            "max_zero_streak": self.max_zero_streak,
            "zero_keys": dict(self._zero_keys),
            "attempts": [a.to_dict() for a in self.attempts[-20:]],
        }
