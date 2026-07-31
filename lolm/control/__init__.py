# Copyright (c) 2026 Qira LLC. All rights reserved.
"""NFET control core — the math that actually decides what the agent does.

This package wires the NFET/LOLM control layer into the runtime as real,
inspectable math rather than branding:

    input/tick -> signals -> NFET fused uncertainty -> NFET event-field energy
              -> action scoring -> decision packet -> execute/idle -> receipt -> UI

Nothing here is decorative. The controller's choice (continue / recall / retrieve
/ verify / branch / revise / run_tool / schedule / nudge / idle / refuse) is the
argmax of a scored, safety/budget-bounded action set over the measured signals,
and every decision is hashed into a receipt whose prose is validated against the
structured trace so the UI can never claim an action that did not happen.

Closed-loop extensions (2026-07):
    state_vector, action_executor, contract, trajectory — see
    docs/NFET_IMPLEMENTATION_PLAN.md
"""

from lolm.control.config import (
    NFET_WEIGHTS,
    NFET_FIELD_WEIGHTS,
    NFET_THRESHOLDS,
    ACTION_SCORE_WEIGHTS,
    VERIFICATION_WEIGHTS,
    RETRIEVAL_WEIGHTS,
    BRANCH_WEIGHTS,
    MEMORY_WRITE_WEIGHTS,
    MEMORY_THRESHOLDS,
    CONTROLLER_VERSION,
)
from lolm.control.signals import ControlSignals, fused_uncertainty
from lolm.control.nfet import NFETField, decide, AGENT_ACTIONS
from lolm.control.decision_packet import DecisionPacket
from lolm.control.receipt import ControlReceipt, build_control_receipt, receipt_hash
from lolm.control.receipt_validator import validate_receipt_claims, FORBIDDEN_WHEN
from lolm.control.state_vector import NfetStateVector, estimate_from_sandbox
from lolm.control.action_executor import ActionExecutor, ExecutionResult
from lolm.control.contract import ContractResult, check_task_contract

__all__ = [
    "ControlSignals", "fused_uncertainty", "NFETField", "decide", "AGENT_ACTIONS",
    "DecisionPacket", "ControlReceipt", "build_control_receipt", "receipt_hash",
    "validate_receipt_claims", "FORBIDDEN_WHEN",
    "NFET_WEIGHTS", "NFET_FIELD_WEIGHTS", "NFET_THRESHOLDS", "ACTION_SCORE_WEIGHTS",
    "VERIFICATION_WEIGHTS", "RETRIEVAL_WEIGHTS", "BRANCH_WEIGHTS",
    "MEMORY_WRITE_WEIGHTS", "MEMORY_THRESHOLDS", "CONTROLLER_VERSION",
    "NfetStateVector", "estimate_from_sandbox",
    "ActionExecutor", "ExecutionResult",
    "ContractResult", "check_task_contract",
]
