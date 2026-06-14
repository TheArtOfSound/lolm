# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Brain-stats snapshot locking — never confuse live stats with receipt stats.

Trust failure #1: the page header reads CURRENT live shared-demo memory while a
run receipt reports the RUN-START snapshot. Both are valid; they must be labelled
separately and never silently disagree. This module locks a snapshot at run start
and diffs it against live so the UI can say exactly which is which.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

SCOPES = ("global_demo", "shared_demo", "user_session", "private_user", "project")

SCOPE_LABEL = {
    "global_demo": "Global demo memory",
    "shared_demo": "Shared demo memory, not private user memory",
    "user_session": "User session memory",
    "private_user": "Private user memory",
    "project": "Project memory index",
}


def snapshot_stats(live: Dict[str, Any], scope: str = "shared_demo",
                   raw_stats_url: Optional[str] = None,
                   now: Optional[str] = None) -> Dict[str, Any]:
    """Lock the run-start memory snapshot from a live /brain/stats payload."""
    scope = scope if scope in SCOPES else "shared_demo"
    return {
        "snapshotId": f"snap-{uuid.uuid4().hex[:12]}",
        "snapshotAt": now or _now_iso(),
        "scope": scope,
        "scopeLabel": SCOPE_LABEL[scope],
        "memories": int(live.get("memories", live.get("memory", 0)) or 0),
        "recalls": int(live.get("recalls", 0) or 0),
        "conversations": int(live.get("conversations", live.get("sessions", 0)) or 0),
        "turns": int(live.get("turns", 0) or 0),
        "rawStatsUrl": raw_stats_url,
    }


def live_vs_snapshot(snapshot: Dict[str, Any], live: Dict[str, Any]) -> Dict[str, Any]:
    """Compare a locked snapshot against current live stats; label both."""
    live_norm = {
        "memories": int(live.get("memories", live.get("memory", 0)) or 0),
        "recalls": int(live.get("recalls", 0) or 0),
        "conversations": int(live.get("conversations", live.get("sessions", 0)) or 0),
        "turns": int(live.get("turns", 0) or 0),
    }
    drifted = any(live_norm[k] != snapshot.get(k) for k in live_norm)
    return {
        "runStartLabel": "Run-start memory snapshot",
        "liveLabel": "Current live memory stats",
        "scopeLabel": snapshot.get("scopeLabel"),
        "runStart": {k: snapshot.get(k) for k in live_norm},
        "live": live_norm,
        "drifted": drifted,
        "note": (
            "Current memory stats may differ because this page is live. "
            "This receipt uses the run-start snapshot."
            if drifted else
            "Run-start snapshot matches current live stats."
        ),
    }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
