# Copyright (c) 2026 Qira LLC. All rights reserved.
"""The decision packet — the structured truth the UI must obey.

Every prompt-time run and autonomous tick produces one. If ``actionTriggered``
is false, the UI may not say the agent acted / checked notes / verified /
branched / retrieved. The receipt validator enforces that against this packet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lolm.control.signals import ControlSignals


@dataclass
class CandidateScore:
    action: str
    score: float
    allowed: bool
    threshold: float
    eligible: bool
    blockedReason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action, "score": round(self.score, 4),
            "allowed": self.allowed, "threshold": round(self.threshold, 4),
            "eligible": self.eligible, "blockedReason": self.blockedReason,
        }


@dataclass
class DecisionPacket:
    id: str
    runId: str
    createdAt: str
    mode: str                      # == selectedAction
    selectedAction: str
    candidateActions: List[CandidateScore]
    signals: ControlSignals
    fieldEnergy: float
    fusedUncertainty: float
    confidence: float
    thresholds: Dict[str, float]
    weights: Dict[str, Dict[str, float]]
    dominantSpikes: List[Dict[str, Any]]
    actionAllowed: bool
    actionTriggered: bool
    reason: str
    decisionSources: List[str]
    tickId: Optional[str] = None
    inputType: str = "user_prompt"
    receiptRequired: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "runId": self.runId, "tickId": self.tickId,
            "createdAt": self.createdAt, "inputType": self.inputType,
            "mode": self.mode, "selectedAction": self.selectedAction,
            "candidateActions": [c.to_dict() for c in self.candidateActions],
            "signals": self.signals.to_dict(),
            "nfet": {
                "fieldEnergy": round(self.fieldEnergy, 4),
                "fusedUncertainty": round(self.fusedUncertainty, 4),
                "idleThreshold": self.thresholds.get("idle"),
                "actionThreshold": self.thresholds.get("act"),
                "finishThreshold": self.thresholds.get("finish"),
                "thresholds": self.thresholds,
                "dominantSpikes": self.dominantSpikes,
                "weights": self.weights,
            },
            "confidence": round(self.confidence, 4),
            "uncertainty": round(self.fusedUncertainty, 4),
            "actionAllowed": self.actionAllowed,
            "actionTriggered": self.actionTriggered,
            "reason": self.reason,
            "decisionSources": self.decisionSources,
            "receiptRequired": self.receiptRequired,
        }
