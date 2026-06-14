# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Control receipt + hash chain — proof of what the controller actually did.

Every prompt-time run and autonomous tick produces a ControlReceipt. The receipt
is hashed (SHA-256 over the canonical JSON minus the hash field) and chained to
the previous receipt, so any change to a decision / action / signal changes the
hash. This is the substrate QEV later seals.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from lolm.control.config import CONTROLLER_VERSION
from lolm.control.decision_packet import DecisionPacket


def canonicalize(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact, UTF-8 stable."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def receipt_hash(receipt_without_hash: Dict[str, Any]) -> str:
    body = dict(receipt_without_hash)
    body.pop("receiptHash", None)
    return hashlib.sha256(canonicalize(body).encode("utf-8")).hexdigest()


class ControlReceipt(dict):
    """A dict subclass so it serializes cleanly and stays explicit."""

    @property
    def hash(self) -> str:
        return self.get("receiptHash", "")


def build_control_receipt(
    decision: DecisionPacket,
    *,
    memory_snapshot: Optional[Dict[str, Any]] = None,
    writer_model: str = "unknown",
    monitor_model: str = "lolm-graft-0.6b",
    autonomy_level: str = "L2_CONTROLLER_ACTIONS",
    input_type: Optional[str] = None,
    trigger_reason: str = "",
    actions: Optional[List[Dict[str, Any]]] = None,
    tools_used: Optional[List[Dict[str, Any]]] = None,
    memory_writes: Optional[List[Dict[str, Any]]] = None,
    low_confidence_spans: Optional[List[Dict[str, Any]]] = None,
    answer_quality: Optional[Dict[str, Any]] = None,
    previous_receipt_hash: Optional[str] = None,
    now: Optional[str] = None,
) -> ControlReceipt:
    """Assemble + hash a control receipt around a decision packet."""
    dp = decision.to_dict()
    action_list = actions if actions is not None else _actions_from_packet(decision)
    triggered_count = sum(1 for a in action_list if a.get("triggered") and a.get("executed"))

    body: Dict[str, Any] = {
        "receiptId": f"rcpt-{uuid.uuid4().hex[:12]}",
        "runId": decision.runId,
        "tickId": decision.tickId,
        "createdAt": now or _now_iso(),
        "writerModel": writer_model,
        "monitorModel": monitor_model,
        "controllerVersion": CONTROLLER_VERSION,
        "inputType": input_type or decision.inputType,
        "triggerReason": trigger_reason,
        "autonomyLevel": autonomy_level,
        "memorySnapshot": memory_snapshot or {"verdict": "no_snapshot"},
        "signals": dp["signals"],
        "decision": dp,
        "actions": action_list,
        "toolsUsed": tools_used or [],
        "memoryWrites": memory_writes or [],
        "lowConfidenceSpans": low_confidence_spans or [],
        "answerQuality": answer_quality or {
            "status": "ungraded", "baselineCompared": False,
        },
        "controllerClaim": {
            "nfetControlled": True,
            "mathBacked": True,
            "traceVisible": True,
            "actionTriggered": decision.actionTriggered,
            "actionCount": triggered_count,
        },
        "previousReceiptHash": previous_receipt_hash,
    }
    body["receiptHash"] = receipt_hash(body)
    return ControlReceipt(body)


def _actions_from_packet(decision: DecisionPacket) -> List[Dict[str, Any]]:
    """A minimal actions array derived from the packet when none is supplied —
    the selected action, marked triggered/executed only if it really fired."""
    triggered = decision.actionTriggered
    return [{
        "type": decision.selectedAction,
        "triggered": triggered,
        "allowed": decision.actionAllowed,
        "executed": False,   # a bare decision has not executed anything yet
        "resultSummary": None,
    }]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
