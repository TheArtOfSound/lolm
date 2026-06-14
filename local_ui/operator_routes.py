# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Endpoint for the autonomous operator — off by default, loopback + token gated.

The operator can run real tools, so it is the most sensitive surface in the
service. Three independent locks:

  1. nginx forwards ONLY /api/demo/ from the public vhost — /api/operator/ is
     never exposed; it is reachable only on loopback (or an SSH tunnel).
  2. It is DISABLED unless ``OPERATOR_SECRET`` is set, and every call must carry
     ``Authorization: Bearer <secret>``.
  3. It refuses to run until the uncertainty monitor (local graft) is loaded —
     no telemetry means no calibrated gate, and a blind operator does not act.

Even past all three, the gate + Operator still hard-gate money/send/delete/
deploy to a human. Defense in depth, then the math.
"""

from __future__ import annotations

import os
from typing import Any, Callable, List, Optional

from pydantic import BaseModel

from lolm.autonomy import RISK_TIERS


class OperatorRunRequest(BaseModel):
    goal: str
    risk_profiles: Optional[List[str]] = None
    max_steps: Optional[int] = None


def register_operator_routes(app: Any, *, build_agent: Callable[[], Any],
                             flywheel: Any, model_ready_fn: Callable[[], bool],
                             secret_env: str = "OPERATOR_SECRET",
                             default_max_steps: int = 8) -> None:
    from fastapi import Header, HTTPException

    def _auth(authorization: Optional[str]) -> None:
        secret = os.environ.get(secret_env)
        if not secret:
            raise HTTPException(status_code=503,
                                detail=f"operator disabled — set {secret_env} to enable")
        if authorization != f"Bearer {secret}":
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.post("/api/operator/run")
    def operator_run(req: OperatorRunRequest,
                     authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        if not model_ready_fn():
            raise HTTPException(status_code=503,
                                detail="uncertainty monitor not loaded yet — the "
                                       "operator does not act without measured uncertainty")
        if not (req.goal or "").strip():
            raise HTTPException(status_code=400, detail="empty goal")
        agent = build_agent()
        steps = req.max_steps or default_max_steps
        steps = max(1, min(int(steps), 20))
        return agent.run(req.goal.strip(), risk_profiles=req.risk_profiles, max_steps=steps)

    @app.get("/api/operator/calibration")
    def operator_calibration(authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        bars = {}
        for tier, alpha in RISK_TIERS.items():
            st = flywheel.selective_bar(alpha)
            bars[tier] = {
                "target_risk": alpha, "feasible": st.feasible,
                "coverage": round(st.coverage, 3),
                "empirical_risk": round(st.empirical_risk, 4),
            }
        return {"flywheel": flywheel.stats(), "selective_bars": bars,
                "note": "selective bars are valid on held-out data; shown here as "
                        "the in-sample picture of how much autonomy the track "
                        "record currently supports per risk tier"}
