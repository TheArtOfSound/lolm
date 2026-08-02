# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Dedicated Evaluation Plane — separate from public demo admission.

Authenticated campaign budgets, queueing, concurrency leases, deterministic
seeds, model/version pinning, and signed campaign receipts.

Reports distinguish: not_admitted, admitted, executed, infrastructure_failed,
model_failed, contract_failed, passed.
"""

from __future__ import annotations

from lolm.reliability.evaluation_plane.campaign import (
    CampaignManifest,
    CampaignQueue,
    CaseRecord,
    CaseStatus,
    sign_campaign_receipt,
)

__all__ = [
    "CampaignManifest",
    "CampaignQueue",
    "CaseRecord",
    "CaseStatus",
    "sign_campaign_receipt",
]
