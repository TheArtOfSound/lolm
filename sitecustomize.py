# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Runtime compatibility patches loaded by Python's standard site initialization.

This file contains only fail-closed, narrowly scoped production corrections. Set
LOLM_DISABLE_ARTIFACT_DELIVERY_PATCH=1 to disable during forensic comparison.
"""
from __future__ import annotations

import os

if os.environ.get("LOLM_DISABLE_ARTIFACT_DELIVERY_PATCH", "").strip().lower() not in {
    "1", "true", "yes", "on",
}:
    try:
        from local_ui.code_agent import CodeAgent
        from local_ui.artifact_manifest_patch import install_patch

        install_patch(CodeAgent)
    except Exception:
        # Startup must remain available; CodeAgent will retain its original
        # fail-closed manifest behavior if optional imports are unavailable.
        pass
