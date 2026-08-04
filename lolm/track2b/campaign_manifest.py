# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Pinned campaign manifest for remote Track 2B competence runs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class Track2BCampaignManifest:
    """Pinned expectations for a remote lolm-code-sse competence campaign."""

    schema: str = "lolm.track2b.campaign.v1"
    expected_server_sha: str = ""
    expected_deployment_id: str = ""
    expected_receipt_key_id: str = ""
    expected_receipt_public_key_sha256: str = ""
    transport: str = "lolm-code-sse"
    isolation_required: str = "bwrap"
    require_trusted_signature: bool = True
    allow_untrusted_local_receipts: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        errs: list[str] = []
        if self.transport != "lolm-code-sse":
            errs.append("transport_must_be_lolm_code_sse")
        if not self.expected_server_sha:
            errs.append("expected_server_sha_required")
        if self.require_trusted_signature:
            if not self.expected_receipt_key_id:
                errs.append("expected_receipt_key_id_required_for_remote")
            if not self.expected_receipt_public_key_sha256:
                errs.append("expected_receipt_public_key_sha256_required_for_remote")
        if self.allow_untrusted_local_receipts and self.require_trusted_signature:
            errs.append("untrusted_local_incompatible_with_require_trusted")
        return errs


def load_manifest(path: str | Path) -> Track2BCampaignManifest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Track2BCampaignManifest(
        **{k: v for k, v in data.items() if k in Track2BCampaignManifest.__dataclass_fields__}
    )


def manifest_from_env() -> Track2BCampaignManifest:
    allow = os.environ.get("LOLM_ALLOW_UNTRUSTED_LOCAL_RECEIPTS", "").strip() in (
        "1", "true", "yes",
    )
    return Track2BCampaignManifest(
        expected_server_sha=os.environ.get("LOLM_EXPECTED_SERVER_SHA", "").strip(),
        expected_deployment_id=os.environ.get("LOLM_EXPECTED_DEPLOYMENT_ID", "").strip(),
        expected_receipt_key_id=os.environ.get("LOLM_EXPECTED_RECEIPT_KEY_ID", "").strip(),
        expected_receipt_public_key_sha256=os.environ.get(
            "LOLM_EXPECTED_RECEIPT_PUBLIC_KEY_SHA256", ""
        ).strip(),
        transport=os.environ.get("LOLM_LIVE_TRANSPORT", "lolm-code-sse").strip() or "lolm-code-sse",
        isolation_required=os.environ.get("LOLM_ISOLATION_REQUIRED", "bwrap").strip() or "bwrap",
        require_trusted_signature=not allow,
        allow_untrusted_local_receipts=allow,
    )
