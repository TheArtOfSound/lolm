# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Track 2B open-ended repository reasoning transports.

Transports are intentionally non-interchangeable experiments:

* ``openai-chat`` — remote model turns driving *local* CodeAgent
* ``lolm-code-sse`` — remote product CodeAgent + remote sandbox over SSE

Results must retain ``transport`` and never be pooled as one experiment.
"""

from lolm.track2b.campaign_manifest import Track2BCampaignManifest, manifest_from_env
from lolm.track2b.classify import RunClass, classify_run
from lolm.track2b.fixtures import (
    MAX_FIXTURE_BYTES,
    build_resume_package,
    fixture_hash,
    validate_fixture_paths,
)
from lolm.track2b.redact import redact_secrets, secrets_present
from lolm.track2b.workspace import (
    build_final_workspace,
    reconstruct_tree,
    tree_hash,
    trees_equal,
)

__all__ = [
    "RunClass",
    "Track2BCampaignManifest",
    "MAX_FIXTURE_BYTES",
    "build_resume_package",
    "fixture_hash",
    "validate_fixture_paths",
    "redact_secrets",
    "secrets_present",
    "build_final_workspace",
    "reconstruct_tree",
    "tree_hash",
    "trees_equal",
    "classify_run",
    "manifest_from_env",
]
