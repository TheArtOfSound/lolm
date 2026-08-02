# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Behavioral reliability architecture (Grand Audit 2026-08-01).

Structural state machines that make capabilities, contracts, artifacts,
failures, controller disagreement, checkpoints, and closure first-class.

Modules (dependency order from audit Appendix E):
  contract_compiler   Dynamic Contract Compiler (DCC)
  capability_graph    Verification Capability Graph (VCG)
  artifact_state      Typed Artifact State Machine (TASM)
  arbiter             Evidence-Gated Controller Arbiter (EGCA)
  failure_ledger      Semantic Failure Ledger (SFL)
  branch_portfolio    Counterfactual Branch Portfolio (CBP)
  checkpoint_store    Last-Known-Green Transaction Store (LGTS)
  closure             Artifact Closure Protocol (ACP)
  session_ledger      Session Intent Ledger (SIL)
  retrieval_bankruptcy Retrieval Bankruptcy Protocol
  confidence          Decomposed confidence metrics
  runtime_manifest    Runtime Self-Description Manifest
  evaluation_plane    Dedicated batch Evaluation Plane
"""

from __future__ import annotations

from lolm.reliability.contract_compiler import (
    CompiledContract,
    Clause,
    compile_contract,
    check_manifest_against_contract,
)
from lolm.reliability.capability_graph import (
    CapabilityGraph,
    CapabilityFact,
    environment_fingerprint,
)
from lolm.reliability.artifact_state import (
    ArtifactRecord,
    ArtifactRegistry,
    infer_language,
)
from lolm.reliability.arbiter import (
    ArbiterDecision,
    ControllerVote,
    select_action,
    PRECEDENCE,
)
from lolm.reliability.failure_ledger import (
    SemanticFailureLedger,
    FailureFingerprint,
)
from lolm.reliability.branch_portfolio import (
    StrategyVector,
    BranchPortfolio,
    hard_feasibility_filter,
)
from lolm.reliability.checkpoint_store import (
    CheckpointStore,
    GreenCheckpoint,
)
from lolm.reliability.closure import (
    ClosureResult,
    evaluate_closure,
    ClosureProtocol,
)
from lolm.reliability.session_ledger import (
    SessionIntentLedger,
    SessionPointers,
)
from lolm.reliability.retrieval_bankruptcy import RetrievalBankruptcy
from lolm.reliability.confidence import ConfidenceBundle, action_certainty_label
from lolm.reliability.runtime_manifest import RuntimeManifest, build_runtime_manifest
from lolm.reliability.progress_budget import EvidenceProgressBudget

__all__ = [
    "CompiledContract",
    "Clause",
    "compile_contract",
    "check_manifest_against_contract",
    "CapabilityGraph",
    "CapabilityFact",
    "environment_fingerprint",
    "ArtifactRecord",
    "ArtifactRegistry",
    "infer_language",
    "ArbiterDecision",
    "ControllerVote",
    "select_action",
    "PRECEDENCE",
    "SemanticFailureLedger",
    "FailureFingerprint",
    "StrategyVector",
    "BranchPortfolio",
    "hard_feasibility_filter",
    "CheckpointStore",
    "GreenCheckpoint",
    "ClosureResult",
    "evaluate_closure",
    "ClosureProtocol",
    "SessionIntentLedger",
    "SessionPointers",
    "RetrievalBankruptcy",
    "ConfidenceBundle",
    "action_certainty_label",
    "RuntimeManifest",
    "build_runtime_manifest",
    "EvidenceProgressBudget",
]
