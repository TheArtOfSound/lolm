# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Oort + Flows tactics for LOLM.

Oort (oortstack.com) is the library of prompts/workflows.
Flows (flows.oortstack.com) is the guided workspace — multi-step playbooks.

LOLM vendors a compact catalog of those playbooks as *tactics*: short,
retrievable rules that supercharge coding/visual agents without claiming
frontier-benchmark supremacy. Infrastructure for z_t / π(z).
"""

from .oort_flows import (  # noqa: F401
    catalog_stats,
    format_tactics_for_prompt,
    match_flow_playbook,
    retrieve_tactics,
    tactics_prompt_block,
)

__all__ = [
    "catalog_stats",
    "format_tactics_for_prompt",
    "match_flow_playbook",
    "retrieve_tactics",
    "tactics_prompt_block",
]
