# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Gated weight-training layer — the part that must NEVER run on autopilot.

Daily ingestion updates memory + the candidate queue immediately (Layers 1-2).
Touching model weights is Layer 3, and it is gated: an adapter is promoted ONLY
when an eval proves improvement with an acceptable regression budget and a clean
license trail. This module is the promotion GATE (real, deterministic logic) and
the training receipt schema. The actual LoRA training is intentionally NOT wired
to fire automatically — it needs a GPU and a curated, licensed, high-signal batch,
and per the architecture it only runs when the eval wall is cleared.

So ``model_weights_changed`` stays ``false`` until a real, eval-proven run is
executed deliberately — and the receipt proves exactly that, rather than claiming
the model "gets smarter every day" when only memory changed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PromotionGate:
    min_improvement: float = 0.02      # eval_after must beat eval_before by this
    max_regressions: int = 0           # how many per-category regressions tolerated
    require_clean_license: bool = True
    min_candidates: int = 200          # don't train a serious adapter on a handful


def evaluate_promotion(*, eval_before: float, eval_after: float, regressions: int,
                       license_clean: bool, gate: Optional[PromotionGate] = None
                       ) -> Dict[str, Any]:
    """Decide whether a trained adapter may go to production. Deterministic."""
    gate = gate or PromotionGate()
    improvement = round(eval_after - eval_before, 4)
    reasons: List[str] = []
    if improvement < gate.min_improvement:
        reasons.append(f"improvement {improvement:+.3f} < required {gate.min_improvement:+.3f}")
    if regressions > gate.max_regressions:
        reasons.append(f"{regressions} regressions > budget {gate.max_regressions}")
    if gate.require_clean_license and not license_clean:
        reasons.append("training data license trail not clean")
    promoted = not reasons
    return {
        "promoted": promoted,
        "improvement": improvement,
        "reason": ("eval improved within regression + license budget"
                   if promoted else "; ".join(reasons)),
    }


def training_receipt(*, base_model: str, method: str, candidate_ids: List[str],
                     licenses: List[str], eval_before: float, eval_after: float,
                     regressions: int, decision: Dict[str, Any],
                     rollback_version: str, qev_seal_id: Optional[str] = None
                     ) -> Dict[str, Any]:
    return {
        "training_run_id": f"train_{uuid.uuid4().hex[:12]}",
        "base_model": base_model, "method": method,
        "training_candidate_ids": candidate_ids[:50], "n_candidates": len(candidate_ids),
        "licenses": sorted(set(licenses)),
        "eval_before": eval_before, "eval_after": eval_after,
        "regressions": regressions,
        "promoted": decision["promoted"], "promotion_reason": decision["reason"],
        "model_weights_changed": decision["promoted"],
        "rollback_version": rollback_version,
        "qev_seal_id": qev_seal_id,
    }


class TrainingPipeline:
    """Reports honest gated status; never trains on its own."""

    def __init__(self, queue, gate: Optional[PromotionGate] = None,
                 has_gpu: bool = False, base_version: str = "LOLM-controller-v0.3"):
        self.queue = queue
        self.gate = gate or PromotionGate()
        self.has_gpu = has_gpu
        self.base_version = base_version

    def status(self) -> Dict[str, Any]:
        ready = self.queue.stats().get("untrained", 0)
        blockers = []
        if not self.has_gpu:
            blockers.append("no GPU on this host — adapter training needs one")
        if ready < self.gate.min_candidates:
            blockers.append(f"only {ready}/{self.gate.min_candidates} clean candidates queued")
        return {
            "layer": "L3_weight_training",
            "auto_runs": False,
            "enabled": not blockers,
            "blockers": blockers,
            "candidates_ready": ready,
            "min_candidates": self.gate.min_candidates,
            "min_improvement": self.gate.min_improvement,
            "max_regressions": self.gate.max_regressions,
            "base_version": self.base_version,
            "model_weights_changed_recently": False,
            "note": ("Weight training is deliberately gated. Memory + retrieval learn "
                     "daily; weights change only behind an eval wall, never on autopilot."),
        }

    def dry_run_plan(self) -> Dict[str, Any]:
        """What WOULD be trained, without training anything."""
        rows = [c for c in self.queue.all() if not c.get("trained")]
        return {
            "would_train": len(rows),
            "licenses": sorted({c.get("license_class") or c.get("license") for c in rows if c}),
            "by_topic": _by(rows, "topic"),
            "method": "LoRA adapter on the NFET controller (action-selection head)",
            "executed": False,
            "reason": "dry run — no GPU / eval-gated; call only after the eval wall clears",
        }


def _by(rows, key) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        k = r.get(key)
        if k:
            out[k] = out.get(k, 0) + 1
    return out
