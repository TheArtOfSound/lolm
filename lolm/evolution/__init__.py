# Copyright (c) 2026 Qira LLC. All rights reserved.
"""LOLM evolution plane — verified product experience → owned weights.

This package turns signed run receipts into Gold trajectories, builds SFT and
preference datasets, trains candidate adapters, and promotes only when offline
and shadow gates prove measurable improvement without safety regression.

First milestone (not continuous pretraining):
  Receipts → Gold → SFT/DPO adapters → frozen eval → shadow → gated promote.

See lolm/evolution/schema.py for the trajectory and manifest contracts.
"""

from __future__ import annotations

from lolm.evolution.schema import (
    CONTROLLER_ACTIONS,
    AdapterRole,
    EvolutionPaths,
    GoldCriteria,
    ModelManifest,
    PreferencePair,
    Trajectory,
    TrajectoryTier,
    VerifierLabel,
    default_paths,
)

__all__ = [
    "CONTROLLER_ACTIONS",
    "AdapterRole",
    "EvolutionPaths",
    "GoldCriteria",
    "ModelManifest",
    "PreferencePair",
    "Trajectory",
    "TrajectoryTier",
    "VerifierLabel",
    "default_paths",
]
