# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Contracts for the LOLM evolution plane.

Design rules (product, not research hobby):
  * Weights learn skills and policies; retrieval holds volatile facts.
  * Only Gold trajectories (independently verified) train weights.
  * Promotion is gated: integrity → frozen suite → real tasks → shadow.
  * Live serving never overwrites previous_known_good on a failed candidate.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


SCHEMA_VERSION = "lolm.evolution.trajectory.v1"
MANIFEST_SCHEMA = "lolm.evolution.manifest.v1"

# Controller / policy labels — stronger signal than synthetic-only scenarios.
CONTROLLER_ACTIONS = (
    "continue",
    "retrieve",
    "read",
    "verify",
    "branch",
    "repair",
    "rollback",
    "abstain",
    "finish",
)


class TrajectoryTier(str, Enum):
    BRONZE = "bronze"  # raw redacted
    SILVER = "silver"  # structural + privacy + license
    GOLD = "gold"  # independently verified, train-safe


class AdapterRole(str, Enum):
    AGENT_POLICY = "lolm-agent-policy"
    CODE_REPAIR = "lolm-code-repair"
    GROUNDED_QA = "lolm-grounded-qa"
    VERIFIER = "lolm-verifier"
    CONTROLLER = "lolm-controller"


class VerifierLabel(str, Enum):
    VERIFIED = "verified"
    INCOMPLETE = "incomplete"
    FALSE_GREEN = "false_green"
    UNSUPPORTED = "unsupported"
    REGRESSION = "regression"
    UNSAFE = "unsafe"


# Volatile fact categories — never train into weights (use retrieval/config).
VOLATILE_FACT_TAGS = frozenset({
    "pricing", "quota", "url", "model_availability", "system_status",
    "docs_version", "law", "news", "product_claim", "customer_specific",
})

# Skills/policies safe (and desired) for weight learning.
SKILL_TAGS = frozenset({
    "repo_inspect", "tool_use", "read_before_edit", "error_interpretation",
    "patch_recovery", "abstain", "cite_evidence", "verify_work",
    "avoid_false_completion", "task_state", "file_selection", "rollback",
})


@dataclass
class EvolutionPaths:
    """Layout under runs/evolution/."""

    root: Path
    raw: Path
    silver: Path
    gold: Path
    datasets: Path
    candidates: Path
    live: Path
    previous: Path
    receipts: Path
    registry: Path

    def ensure(self) -> "EvolutionPaths":
        for p in (
            self.root, self.raw, self.silver, self.gold, self.datasets,
            self.candidates, self.live, self.previous, self.receipts,
        ):
            p.mkdir(parents=True, exist_ok=True)
        if not self.registry.exists():
            self.registry.write_text("")
        return self


def default_paths(repo_root: Optional[Path] = None) -> EvolutionPaths:
    base = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    root = base / "runs" / "evolution"
    return EvolutionPaths(
        root=root,
        raw=root / "raw",
        silver=root / "silver",
        gold=root / "gold",
        datasets=root / "datasets",
        candidates=root / "candidates",
        live=root / "live",
        previous=root / "previous",
        receipts=root / "receipts",
        registry=root / "registry.jsonl",
    ).ensure()


@dataclass
class Trajectory:
    """Machine-readable product trajectory for training.

    Bronze may be incomplete. Gold requires independent_oracle=pass and the
    checks in GoldCriteria / gold_filter.
    """

    task: str = ""
    task_bucket: str = "unknown"
    initial_repository_tree: str = ""
    model: str = ""
    provider: str = ""
    messages: List[Dict[str, str]] = field(default_factory=list)
    files_read: List[str] = field(default_factory=list)
    actions_proposed: List[Dict[str, Any]] = field(default_factory=list)
    actions_rejected: List[Dict[str, Any]] = field(default_factory=list)
    mutations_applied: List[Dict[str, Any]] = field(default_factory=list)
    commands_run: List[str] = field(default_factory=list)
    stdout: List[str] = field(default_factory=list)
    stderr: List[str] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    final_tree_hash: str = ""
    independent_oracle: str = "unknown"  # pass | fail | unknown
    user_correction: Optional[str] = None
    trust_abort: bool = False
    receipt_signature_valid: bool = False
    # Provenance
    source: str = ""
    source_path: str = ""
    run_id: str = ""
    tier: str = TrajectoryTier.BRONZE.value
    skill_tags: List[str] = field(default_factory=list)
    volatile_tags: List[str] = field(default_factory=list)
    training_permitted: bool = True
    benchmark_contaminated: bool = False
    privacy_cleared: bool = False
    fixture_immutable: bool = False
    schema_version: str = SCHEMA_VERSION
    harvested_at: int = 0
    trajectory_id: str = ""
    content_sha256: str = ""

    def compute_id(self) -> str:
        body = {
            "task": self.task,
            "messages": self.messages,
            "mutations_applied": self.mutations_applied,
            "final_tree_hash": self.final_tree_hash,
            "model": self.model,
            "run_id": self.run_id,
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.content_sha256 = digest
        self.trajectory_id = digest[:24]
        return self.trajectory_id

    def to_dict(self) -> Dict[str, Any]:
        if not self.trajectory_id:
            self.compute_id()
        if not self.harvested_at:
            self.harvested_at = int(time.time())
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Trajectory":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class PreferencePair:
    prompt: str
    chosen: str
    rejected: str
    task_bucket: str = "unknown"
    reason: str = ""
    trajectory_id: str = ""
    pair_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        if not self.pair_id:
            blob = f"{self.prompt}|{self.chosen}|{self.rejected}"
            self.pair_id = hashlib.sha256(blob.encode()).hexdigest()[:20]
        return asdict(self)

    def to_trl_row(self) -> Dict[str, Any]:
        """Conversational preference row for Hugging Face TRL DPOTrainer."""
        return {
            "prompt": [{"role": "user", "content": self.prompt}],
            "chosen": [{"role": "assistant", "content": self.chosen}],
            "rejected": [{"role": "assistant", "content": self.rejected}],
            "task_bucket": self.task_bucket,
            "reason": self.reason,
            "pair_id": self.pair_id or self.to_dict()["pair_id"],
        }


@dataclass
class ControllerExample:
    state: Dict[str, Any]
    correct_action: str
    trajectory_id: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerifierExample:
    task_contract: str
    diff: str
    test_output: str
    artifact: str
    receipt_summary: str
    claimed_completion: str
    label: str
    trajectory_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GoldCriteria:
    """Requirements for a trajectory to enter the Gold training set."""

    require_receipt_signature: bool = True
    require_oracle_pass: bool = True
    require_no_trust_abort: bool = True
    require_privacy_cleared: bool = True
    require_model_known: bool = True
    require_no_contamination: bool = True
    require_training_permitted: bool = True
    require_no_volatile_only: bool = True  # reject pure volatile-fact dumps
    min_messages: int = 1


@dataclass
class DataThresholds:
    """Trigger training by quality mass, not every message."""

    min_gold_trajectories: int = 500
    min_preference_pairs: int = 250
    min_per_bucket: int = 50
    require_no_integrity_alert: bool = True
    require_budget: bool = True
    require_no_active_campaign: bool = True


@dataclass
class ReplayMixture:
    """Batch mixture to limit catastrophic forgetting."""

    new_verified: float = 0.40
    historical_hard: float = 0.30
    broad_rehearsal: float = 0.20
    safety_refusal: float = 0.10

    def normalize(self) -> "ReplayMixture":
        total = self.new_verified + self.historical_hard + self.broad_rehearsal + self.safety_refusal
        if total <= 0:
            return ReplayMixture()
        return ReplayMixture(
            new_verified=self.new_verified / total,
            historical_hard=self.historical_hard / total,
            broad_rehearsal=self.broad_rehearsal / total,
            safety_refusal=self.safety_refusal / total,
        )


@dataclass
class ModelManifest:
    """Every promoted (or rejected) model version evidence record."""

    model_version: str
    base_model: str
    base_revision: str = ""
    adapter_role: str = AdapterRole.AGENT_POLICY.value
    adapter_sha256: str = ""
    training_code_sha: str = ""
    dataset_sha256: str = ""
    sft_examples: int = 0
    preference_pairs: int = 0
    replay_examples: int = 0
    offline_score_before: float = 0.0
    offline_score_after: float = 0.0
    track2b_before: float = 0.0
    track2b_after: float = 0.0
    trust_aborts: int = 0
    shadow_wins: int = 0
    shadow_losses: int = 0
    decision: str = "pending"  # promoted | rejected | candidate | rolled_back
    previous_version: str = ""
    canary_pct: float = 0.0
    ts: int = 0
    schema_version: str = MANIFEST_SCHEMA
    notes: str = ""
    gates: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        if not self.ts:
            self.ts = int(time.time())
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelManifest":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return path


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if isinstance(d, dict):
                out.append(d)
        except json.JSONDecodeError:
            continue
    return out
