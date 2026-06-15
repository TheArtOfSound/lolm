# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Self-driving release pipeline — ship daily, behind hard proof gates.

Not "open a PR and wait forever." The agent learns, patches, tests, evals, and
ships ON ITS OWN — but every irreversible step (merge to main, publish npm, deploy)
is guarded by a deterministic gate that must pass with proof, and every run leaves
a receipt + a rollback command. If a gate fails, the run blocks itself with the
exact failed command instead of pretending it shipped.

The non-negotiables (the owner's line): tests, evals, and rollback are never
removed — without them it is "a repo-destroyer with API keys," not autonomy.
"""

from lolm.release.gates import (GateResult, MergeGate, PublishGate, DeployGate,
                                 secret_scan, protected_files_touched, evaluate_gates)
from lolm.release.versioning import (canary_version, bump_patch, bump_minor, bump_major,
                                     read_pkg_version, write_pkg_version)
from lolm.release.receipt import DailyReceipt, VERDICTS, receipt_to_markdown

__all__ = [
    "GateResult", "MergeGate", "PublishGate", "DeployGate", "secret_scan",
    "protected_files_touched", "evaluate_gates", "canary_version", "bump_patch",
    "bump_minor", "bump_major", "read_pkg_version", "write_pkg_version",
    "DailyReceipt", "VERDICTS", "receipt_to_markdown",
]
