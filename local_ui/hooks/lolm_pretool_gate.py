#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""PreToolUse hook: enforce LOLM's autonomy gate on Claude Code's real tools.

This is the "enforced, not optional" half of making Claude do what LOLM does.
Claude Code calls this before every tool use with the tool name + input on
stdin. We classify the action's mechanical risk, run the same AutonomyGate the
receipt path uses, and:

  * HARD HUMAN GATE (payment / transfer / send / email / delete / deploy) or an
    ESCALATE decision  ->  permissionDecision "ask": a human approves. This is
    the irreversible-action ceiling from lolm.autonomy, in the math not a doc.
  * everything else     ->  "allow" (advisory; the receipt is the record).

FAIL-OPEN by contract: any error, missing dep, or unparseable payload returns
allow. A monitoring hook must never be able to brick the session.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _allow(reason: str = "") -> dict:
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "allow"}}
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return out


def _ask(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "ask",
                                   "permissionDecisionReason": reason}}


# --- map a Claude Code tool call onto an action_kind -----------------------

_DELETE_RE = re.compile(
    r"\brm\s+-[a-z]*[rf]|\brm\s+-[a-z]*\s|\bunlink\b|\bshred\b|\bdrop\s+table\b"
    r"|\btruncate\b|\bgit\s+branch\s+-D\b|\bgit\s+push\b.*--force|\b--force\b.*\bgit\s+push"
    r"|\bgit\s+reset\s+--hard\b", re.I)
_DEPLOY_RE = re.compile(
    r"\bgit\s+push\b|\bwrangler\s+(deploy|publish)|\bnpm\s+publish\b|\byarn\s+publish\b"
    r"|\bsystemctl\s+(restart|stop|start)|\bkubectl\s+apply|\bdocker\s+push\b"
    r"|\bgh\s+release\s+create|\bterraform\s+apply|\bvercel\s+(deploy|--prod)"
    r"|\bscp\b|\brsync\b.*::|\brsync\b.*@", re.I)
_SEND_RE = re.compile(r"\bsendmail\b|\bmail\s+-s\b|\bmsmtp\b|\bgh\s+gist\s+create\b", re.I)
_POST_RE = re.compile(
    r"\bcurl\b.*-X\s*(POST|PUT|PATCH|DELETE)|\bcurl\b.*(--data|-d\s)|\bgh\s+pr\s+create\b"
    r"|\bgh\s+issue\s+create\b|\bwget\b.*--post", re.I)


_READ_CMD_RE = re.compile(
    r"^\s*(ls|cat|head|tail|grep|rg|find|echo|pwd|wc|file|stat|which|type|env|date"
    r"|git\s+(status|log|diff|show|branch\b(?!\s+-)|remote)|ps|df|du|whoami|uname)\b", re.I)


def _bash_action(cmd: str) -> str:
    if _DELETE_RE.search(cmd):
        return "delete"
    if _DEPLOY_RE.search(cmd):
        return "deploy"
    if _SEND_RE.search(cmd):
        return "send"
    if _POST_RE.search(cmd):
        return "post"
    # Read-only commands (no side effect) are read-tier — no advisory noise.
    if _READ_CMD_RE.match(cmd) and "|" not in cmd and ">" not in cmd:
        return "read"
    return "run_code"


def _mcp_action(tool: str) -> str:
    t = tool.lower()
    if any(k in t for k in ("payment", "transfer", "trade", "checkout", "charge")):
        return "payment"
    if any(k in t for k in ("send", "email", "draft", "message")):
        return "send"
    if "delete" in t or "remove" in t:
        return "delete"
    if any(k in t for k in ("deploy", "publish", "release")):
        return "deploy"
    if any(k in t for k in ("create", "update", "write", "post", "label")):
        return "post"
    return "read"


def classify(tool_name: str, tool_input: dict) -> str:
    name = tool_name or ""
    if name == "Bash":
        return _bash_action(str(tool_input.get("command", "")))
    if name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        return "edit"
    if name in ("Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"):
        return "read"
    if name.startswith("mcp__"):
        return _mcp_action(name)
    return "read"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps(_allow()))
        return
    try:
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {}) or {}
        action_kind = classify(tool_name, tool_input)

        from local_ui.claude_harness import gate_only
        result = gate_only(action_kind)          # mechanical risk; no telemetry
        decision = result["decision"]
        hard = result["hard_human_gated"]

        if hard:
            print(json.dumps(_ask(
                f"LOLM gate: '{action_kind}' is an irreversible/outward action — "
                f"hard-gated to a human regardless of confidence. {decision['reason']}")))
            return
        if decision["mode"] == "escalate":
            print(json.dumps(_ask(
                f"LOLM gate: {tool_name} classified '{action_kind}' (tier "
                f"{result['tier']}) escalated — {decision['reason']}")))
            return
        # act / gather both proceed; gather is an advisory "verify" note.
        note = "" if decision["mode"] == "act" else f"LOLM gate suggests verifying: {decision['reason']}"
        print(json.dumps(_allow(note)))
    except Exception as exc:
        # Fail-open: never block on our own error.
        print(json.dumps(_allow(f"lolm gate skipped (error: {exc})"[:200])))


if __name__ == "__main__":
    main()
