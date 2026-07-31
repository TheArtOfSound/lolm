# Copyright (c) 2026 Qira LLC. All rights reserved.
"""JSON-serializable schemas for NFET control receipts and harness rows."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ActionEvent(TypedDict, total=False):
    action: str
    consumed: bool
    ms: float
    side_effects: List[str]
    error: str


class NfetReceiptBlock(TypedDict, total=False):
    nfet_coding: bool
    mode: str  # graft | synthetic | code_head | mixed
    graft_available: bool
    code_head: bool
    controller_version: str
    state: Dict[str, Any]
    actions: List[ActionEvent]
    contract: Dict[str, Any]
    timeline: List[Dict[str, Any]]


class HarnessArmResult(TypedDict, total=False):
    arm: str  # plain | observer | active
    task_id: str
    trial: int
    passed: bool
    wall_s: float
    model_calls: int
    steps: int
    overclaim: bool
    nfet_actions: List[ActionEvent]
    error: str


CONTROLLER_VERSION = "nfet-control-v1-2026-07"
