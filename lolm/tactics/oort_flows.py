# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Load and retrieve Oort/Flows tactics for LOLM agents.

Catalog source: Flows by Oort (140 guided flows → ~740 step tactics),
vendored at ``lolm/tactics/oort_flows_catalog.json`` so production does not
need the Flows checkout. Rebuild with scripts/import_oort_flows_tactics.py
when the Flows library updates.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_CATALOG_NAME = "oort_flows_catalog.json"


def catalog_path() -> Path:
    return Path(__file__).resolve().parent / _CATALOG_NAME


@lru_cache(maxsize=1)
def _load_catalog() -> Dict[str, Any]:
    path = catalog_path()
    if not path.is_file():
        return {
            "schema": "missing",
            "flow_count": 0,
            "tactic_count": 0,
            "categories": {},
            "flows": [],
            "tactics": [],
        }
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def catalog_stats() -> Dict[str, Any]:
    c = _load_catalog()
    return {
        "schema": c.get("schema"),
        "origin": c.get("origin"),
        "path": str(catalog_path()),
        "flow_count": int(c.get("flow_count") or 0),
        "tactic_count": int(c.get("tactic_count") or 0),
        "categories": c.get("categories") or {},
        "present": catalog_path().is_file(),
    }


def _keywords(text: str) -> set:
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_+-]{2,}", (text or "").lower()))


# Domain boosts: map task language → tags that exist on Oort/Flows tactics.
_DOMAIN_BOOSTS: Tuple[Tuple[str, str], ...] = (
    ("snake", "game"), ("canvas", "canvas"), ("game", "game"),
    ("visual", "browser"), ("html", "browser"), ("browser", "browser"),
    ("mcp", "mcp"), ("tool", "tool"), ("schema", "schema"),
    ("memory", "memory"), ("session", "session"), ("context", "context"),
    ("compact", "compaction"), ("plan", "plan"), ("todo", "todo"),
    ("orchestr", "orchestration"), ("multi-agent", "multi-agent"),
    ("sub-agent", "sub"), ("dispatch", "dispatch"), ("spawn", "spawn"),
    ("fork", "fork"), ("verify", "verification"), ("adversarial", "adversarial"),
    ("security", "security"), ("audit", "audit"), ("harness", "harness"),
    ("eval", "evals"), ("observab", "observability"), ("trace", "trace"),
    ("retry", "retry"), ("error", "error"), ("debug", "debug"),
    ("qa", "qa"), ("auth", "auth"), ("payment", "payment"),
    ("accessib", "accessibility"), ("a11y", "accessibility"),
    ("launch", "launch"), ("deploy", "deploy"), ("saas", "saas"),
    ("react", "react"), ("api", "api"), ("persist", "persistent"),
    ("agent", "agent"), ("loop", "loop"), ("prompt", "prompt"),
    ("permission", "permission"), ("secret", "secrets"),
    ("supply", "supply"), ("red team", "red"), ("incident", "incident"),
)


def _task_keys(task: str, extra_tags: Optional[Sequence[str]] = None) -> set:
    keys = _keywords(task)
    tl = (task or "").lower()
    for word, tag in _DOMAIN_BOOSTS:
        if word in tl:
            keys.add(tag)
    for t in extra_tags or []:
        if t:
            keys.add(str(t).lower())
    return keys


def retrieve_tactics(
    task: str,
    limit: int = 6,
    *,
    categories: Optional[Sequence[str]] = None,
    extra_tags: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Score catalog tactics for *task*; return top N (no mutation)."""
    c = _load_catalog()
    tactics = c.get("tactics") or []
    if not tactics:
        return []
    keys = _task_keys(task, extra_tags)
    cat_filter = {str(x).lower() for x in (categories or []) if x}
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for t in tactics:
        if cat_filter:
            if str(t.get("category") or "").lower() not in cat_filter:
                continue
        tags = set(str(x).lower() for x in (t.get("tags") or []))
        blob = " ".join([
            str(t.get("title") or ""),
            str(t.get("body") or ""),
            str(t.get("flow_title") or ""),
            str(t.get("category") or ""),
            " ".join(tags),
        ]).lower()
        score = 0.0
        score += 3.2 * len(keys & tags)
        score += 1.1 * sum(1 for k in keys if len(k) > 3 and k in blob)
        # Prefer agent/harness/memory categories slightly for coding agents.
        cat = str(t.get("category") or "")
        if cat in (
            "Agent Architecture", "Harness Engineering", "Memory & Context",
            "Agent QA & Security", "MCP & Tooling", "Debugging", "QA",
        ):
            score += 0.35
        if cat == "App Builder" and any(
            k in keys for k in ("game", "react", "saas", "auth", "browser", "html")
        ):
            score += 0.5
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    lim = max(1, min(int(limit or 6), 16))
    return [t for _, t in scored[:lim]]


def match_flow_playbook(
    task: str,
    *,
    limit: int = 1,
) -> List[Dict[str, Any]]:
    """Return the best-matching full flow playbook(s) for plan injection."""
    c = _load_catalog()
    flows = c.get("flows") or []
    if not flows:
        return []
    keys = _task_keys(task)
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for f in flows:
        tags = set(str(x).lower() for x in (f.get("tags") or []))
        blob = " ".join([
            str(f.get("title") or ""),
            str(f.get("description") or ""),
            str(f.get("category") or ""),
            str(f.get("slug") or ""),
            " ".join(tags),
            " ".join(s.get("title") or "" for s in (f.get("steps") or [])[:6]),
        ]).lower()
        score = 2.5 * len(keys & tags)
        score += 1.0 * sum(1 for k in keys if len(k) > 3 and k in blob)
        # Strong slug/title hits
        slug = str(f.get("slug") or "").replace("-", " ")
        for k in keys:
            if len(k) > 4 and k in slug:
                score += 2.0
        if score > 1.5:
            scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    lim = max(1, min(int(limit or 1), 3))
    return [f for _, f in scored[:lim]]


def format_tactics_for_prompt(
    tactics: Sequence[Dict[str, Any]],
    *,
    heading: str = "OORT/FLOWS TACTICS",
) -> str:
    if not tactics:
        return ""
    lines = [
        f"\n── {heading} (from Oort library + Flows playbooks — apply when relevant) ──",
    ]
    for i, t in enumerate(tactics, 1):
        title = (t.get("title") or t.get("id") or "tactic")[:120]
        cat = t.get("category") or ""
        body = (t.get("body") or "")[:520]
        lines.append(f"{i}. [{cat}] {title}")
        lines.append(f"   {body}")
    lines.append("── end oort/flows tactics ──\n")
    return "\n".join(lines)


def format_playbook_for_prompt(flow: Dict[str, Any]) -> str:
    if not flow:
        return ""
    title = flow.get("title") or flow.get("slug") or "flow"
    cat = flow.get("category") or ""
    lines = [
        f"\n── MATCHED FLOWS PLAYBOOK: {title} ({cat}) ──",
        f"Slug: {flow.get('slug')}",
    ]
    if flow.get("description"):
        lines.append(str(flow["description"])[:280])
    lines.append("Execute steps in order (adapt to the sandbox; skip irrelevant):")
    for s in (flow.get("steps") or [])[:10]:
        order = s.get("order") or "?"
        st = s.get("title") or ""
        purpose = (s.get("purpose") or "")[:160]
        lines.append(f"  {order}. {st}" + (f" — {purpose}" if purpose else ""))
    lines.append("── end playbook ──\n")
    return "\n".join(lines)


def tactics_prompt_block(task: str, limit: int = 5) -> str:
    """Retrieve top tactics + best playbook for agent injection."""
    try:
        tac = retrieve_tactics(task, limit=limit)
        block = format_tactics_for_prompt(tac)
        books = match_flow_playbook(task, limit=1)
        if books and (not tac or _playbook_is_strong(task, books[0])):
            block += format_playbook_for_prompt(books[0])
        return block
    except Exception:
        return ""


def _playbook_is_strong(task: str, flow: Dict[str, Any]) -> bool:
    """Only inject a full playbook when the match is clear enough."""
    keys = _task_keys(task)
    tags = set(str(x).lower() for x in (flow.get("tags") or []))
    title_k = _keywords(str(flow.get("title") or "") + " " + str(flow.get("slug") or ""))
    return len(keys & tags) >= 2 or len(keys & title_k) >= 2


def plan_steps_from_playbook(task: str) -> List[Dict[str, str]]:
    """Plan steps suitable for z_t.P when a Flows playbook matches."""
    books = match_flow_playbook(task, limit=1)
    if not books or not _playbook_is_strong(task, books[0]):
        return []
    flow = books[0]
    out: List[Dict[str, str]] = []
    for s in (flow.get("steps") or [])[:8]:
        order = int(s.get("order") or len(out) + 1)
        title = (s.get("title") or f"step-{order}").strip()
        purpose = (s.get("purpose") or "").strip()
        text = title if not purpose else f"{title}: {purpose}"
        out.append({
            "id": f"flow-{flow.get('slug')}-{order}",
            "text": text[:200],
            "flow_slug": str(flow.get("slug") or ""),
        })
    return out


def iter_tactics_for_seed() -> List[Dict[str, Any]]:
    """All catalog tactics in technique-library shape."""
    c = _load_catalog()
    rows = []
    for t in c.get("tactics") or []:
        rows.append({
            "id": t.get("id"),
            "title": t.get("title"),
            "body": t.get("body"),
            "tags": t.get("tags") or [],
            "source": "oort-flows",
            "category": t.get("category"),
            "flow_slug": t.get("flow_slug"),
        })
    return rows
