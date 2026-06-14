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
    "You are the PLANNER for an autonomous operator. Each turn choose ONE next "
    "step toward the GOAL using only these tools:\n"
    "  web_read{url}     fetch a public web page's text (research, read-only)\n"
    "  run_python{code}  run Python in an isolated sandbox (dev; stdout/stderr)\n"
    "  shell_read{cmd}   a READ-ONLY shell command (ops; ls/cat/df/dig/"
    "systemctl status/...)\n\n"
    "Reply with ONE JSON object and nothing else:\n"
    '  {"action":"tool","tool":"<name>","args":{...},"reason":"why",'
    '"risk_profiles":["financial"|"legal"|"medical"|"quantitative"|...]}\n'
    "or, when the goal is achieved:\n"
    '  {"action":"finish","answer":"<final answer>"}\n\n'
    "Rules: never invent tools; prefer read-only steps; if the goal needs money/"
    "sending/deleting/deploying you may PROPOSE it (it will be hard-gated to a "
    "human) and must say so in reason. Set risk_profiles when the step touches "
    "money, law, medicine, or exact quantities."
)


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
        plan = extract_plan(text or "")
        if not plan or plan.get("action") not in ("tool", "finish"):
            # No valid plan -> treat the reply as a final answer, never guess a tool.
            return {"action": "finish", "answer": (text or "").strip()[:2000]}
        return plan
