# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Frontier-backed planner — the model proposes the next gated tool action.

The planner is the only place the language model touches the action loop, and it
has NO power: it merely *proposes* a tool call as JSON. The autonomy gate decides
whether that proposal runs, and the Operator hard-gates the dangerous kinds.
So a hijacked or hallucinated plan cannot, by construction, execute money/send/
delete/deploy or act past the calibrated bar — the model suggests, the math
disposes.

``chat_fn(messages) -> text`` is injected (provider-agnostic, testable). A
malformed reply degrades to a graceful "finish" rather than a guess.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List

ChatFn = Callable[[List[Dict[str, str]]], str]

TOOL_SPEC = (
    "You are the PLANNER for an autonomous operator. Output ONE JSON object and "
    "nothing else.\n\n"
    "Tools — use the name EXACTLY as written, with no braces:\n"
    '  web_read     args {"url": "https://..."}   fetch a public web page (read-only)\n'
    '  run_python   args {"code": "..."}           run Python in a sandbox\n'
    '  shell_read   args {"cmd": "df -h /"}        ONE read-only shell command\n\n'
    "To take a step, copy this shape exactly:\n"
    '  {"action": "tool", "tool": "shell_read", "args": {"cmd": "free -m"}, '
    '"reason": "check memory"}\n'
    "When the goal is fully answered:\n"
    '  {"action": "finish", "answer": "<the answer>"}\n\n'
    'Rules: "tool" is EXACTLY web_read, run_python, or shell_read — never add '
    "{cmd}/{url}/{code} braces. Prefer read-only steps. shell_read runs ONE "
    "command with no pipes or redirects. Add \"risk_profiles\":[...] (e.g. "
    '"financial","legal","medical","quantitative") when the step touches those. '
    "Money/sending/deleting/deploying will be hard-gated to a human."
)

_TOOL_NAMES = {"web_read", "run_python", "shell_read"}


def normalize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce the model's common schema variants into the canonical shape.

    Real 70B replies flatten ``{"action":"web_read",...}`` or echo the spec's
    placeholder as ``"tool":"shell_read{cmd}"``. Rather than reject a basically-
    correct plan, repair these deterministically — the gate still decides what
    runs, so lenient parsing here costs no safety.
    """
    if not isinstance(plan, dict):
        return {}
    action = plan.get("action")
    # Model put the tool name in "action".
    if action in _TOOL_NAMES:
        plan = {"action": "tool", "tool": action,
                "args": plan.get("args") or {},
                "reason": plan.get("reason", ""),
                "risk_profiles": plan.get("risk_profiles"),
                "url": plan.get("url"), "cmd": plan.get("cmd"), "code": plan.get("code")}
        action = "tool"
    if action == "tool":
        tool = re.sub(r"\{.*?\}", "", str(plan.get("tool", ""))).strip()
        plan["tool"] = tool
        args = plan.get("args")
        if not isinstance(args, dict):
            args = {}
        # Some replies hoist the single arg to the top level.
        for k in ("url", "cmd", "code"):
            if k not in args and plan.get(k):
                args[k] = plan[k]
        plan["args"] = args
    return plan


def extract_plan(text: str) -> Dict[str, Any]:
    """Pull the first JSON object out of a model reply; {} if none parses."""
    if not text:
        return {}
    # Strip code fences, then grab the first balanced-looking {...}.
    cleaned = re.sub(r"```(?:json)?", "", text)
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return {}
    blob = m.group(0)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Trim to the first top-level object if the model appended prose.
        depth = 0
        for i, ch in enumerate(blob):
            depth += (ch == "{") - (ch == "}")
            if depth == 0:
                try:
                    return json.loads(blob[: i + 1])
                except json.JSONDecodeError:
                    return {}
        return {}


class FrontierPlanner:
    def __init__(self, chat_fn: ChatFn):
        self.chat_fn = chat_fn

    def __call__(self, goal: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        lines = []
        for h in history[-8:]:
            lines.append(f"- {h.get('tool')}({json.dumps(h.get('args'))}) "
                         f"[{h.get('decision')}] -> {h.get('outcome')}: "
                         f"{h.get('observation')}")
        user = (f"GOAL: {goal}\n\nSTEPS SO FAR:\n"
                + ("\n".join(lines) if lines else "(none yet)")
                + "\n\nReturn the next step as a single JSON object.")
        try:
            text = self.chat_fn([{"role": "system", "content": TOOL_SPEC},
                                 {"role": "user", "content": user}])
        except Exception as exc:
            return {"action": "finish", "answer": f"planner error: {exc}"[:300]}
        plan = normalize_plan(extract_plan(text or ""))
        if plan.get("action") == "tool" and plan.get("tool") in _TOOL_NAMES:
            return plan
        if plan.get("action") == "finish":
            return plan
        # No usable plan -> treat the reply as a final answer, never guess a tool.
        return {"action": "finish", "answer": (text or "").strip()[:2000]}
