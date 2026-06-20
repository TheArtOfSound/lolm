# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Agentic coding loop — the agent writes code, runs it, reads the failure, fixes it.

The "Claude Code" inner loop, on top of LOLM's isolated sandbox: the 70B proposes ONE
action per turn (write a file / run a command / finish), the loop executes it for real
in the bwrap jail, feeds the actual stdout+exit back, and iterates until the task works
or a step budget is hit. Every action is real and recorded — no pretending a command
ran. The model never executes anything itself; the loop is the only thing that touches
the sandbox, so the same isolation + deny-list still apply.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterator, List, Optional

SYSTEM = (
    "You are a coding agent in a SANDBOXED Linux environment (python3 + node available, "
    "NO network). Achieve the TASK by emitting EXACTLY ONE action per turn as a single "
    "JSON object and nothing else:\n"
    '  {"action":"write_file","path":"main.py","content":"<full file contents>","why":"<short>"}\n'
    '  {"action":"run","command":"python3 main.py","why":"<short>"}\n'
    '  {"action":"finish","summary":"<what you built and that it works>"}\n'
    "Workflow: write code to a file, then RUN it. After each run you are shown the REAL "
    "stdout/stderr/exit code — if it failed, write a corrected file and run again. "
    "CRITICAL: you MUST actually run the code and see exit 0 BEFORE you finish. Never "
    "finish just because you wrote a file — run it first. Do NOT include explanations "
    "outside the JSON. Do NOT use the network. Respond with ONLY the JSON object for the "
    "next action."
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON action object out of a model reply (tolerates ``` fences,
    leading prose, and minor drift)."""
    if not text:
        return None
    t = text.strip()
    # strip code fences
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.IGNORECASE | re.MULTILINE)
    # find the first balanced {...}
    start = t.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    chunk = t[start:i + 1]
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict) and obj.get("action"):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = t.find("{", start + 1)
    return None


class CodeAgent:
    def __init__(self, sandbox: Any, chat_fn: Callable[[List[Dict[str, str]]], str],
                 max_steps: int = 8, run_timeout: int = 15,
                 isolated: Optional[bool] = True):
        self.sb = sandbox
        self.chat = chat_fn
        self.max_steps = max_steps
        self.run_timeout = run_timeout
        self.isolated = isolated          # public loop forces True (bwrap jail)
        self.actions: List[Dict[str, Any]] = []

    def _context(self) -> str:
        """Compact running transcript of what's been done + the latest results, so the
        model can iterate and fix."""
        if not self.actions:
            return "\n\n(No actions yet. Start by writing a file.)"
        lines = ["\n\nSO FAR:"]
        for a in self.actions[-6:]:
            if a["kind"] == "write_file":
                lines.append(f"- wrote {a['path']} ({a.get('bytes', 0)} bytes)")
            elif a["kind"] == "run":
                r = a["result"]
                out = ((r.get("stdout") or "") + (r.get("stderr") or "")).strip()
                tag = "BLOCKED" if r.get("blocked") else f"exit {r.get('exit_code')}"
                lines.append(f"- ran `{a['command']}` → {tag}\n  output: {out[:600] or '(none)'}")
        last = self.actions[-1]
        if last["kind"] == "run" and not last["result"].get("blocked") \
                and last["result"].get("exit_code") == 0:
            lines.append("\nThe last run SUCCEEDED (exit 0). If its output satisfies the "
                         "TASK, emit a finish action NOW — do not re-run the same command. "
                         "Only continue if something still needs fixing.")
        else:
            lines.append("\nEmit the next JSON action (fix the file if the last run failed, "
                         "or run it if you haven't yet).")
        return "\n".join(lines)

    def run(self, task: str) -> Iterator[Dict[str, Any]]:
        yield {"event": "code_start", "data": {"task": task, "sandbox": self.sb.id}}
        ran_any = False
        nudges = 0
        for step in range(self.max_steps):
            extra = ""
            if nudges:
                extra = ("\n\nYou have NOT run the code yet. Emit a {\"action\":\"run\",...} "
                         "action now — do not finish until you have actually run it.")
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"TASK: {task}{self._context()}{extra}"}]
            try:
                raw = self.chat(msgs)
            except Exception as exc:
                yield {"event": "error", "data": {"error": f"model failed: {exc}"[:200]}}
                return
            action = _extract_json(raw)
            if not action:
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "no parseable action from the model; stopping",
                       "raw": (raw or "")[:300]}}
                break
            act = action.get("action")
            why = action.get("why", "")
            if act == "finish":
                # Hard guard: don't accept "finish" until the code has actually run.
                if not ran_any and nudges < 2:
                    nudges += 1
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish without running the code — pushing it to run first"}}
                    continue
                yield {"event": "code_done", "data": {"summary": action.get("summary", ""),
                       "steps": step, "ran": ran_any}}
                return
            if act == "write_file":
                path = action.get("path", "main.txt")
                content = action.get("content", "")
                try:
                    fc = self.sb.write_file(path, content, reason=why)
                except Exception as exc:
                    yield {"event": "agent_note", "data": {"text": f"write failed: {exc}"[:160]}}
                    continue
                self.actions.append({"kind": "write_file", "path": path, "bytes": len(content)})
                yield {"event": "file_changed", "data": {"path": path, "reason": why,
                       "diff": (fc.get("diff") or "")[:2000], "bytes": len(content)}}
            elif act == "run":
                cmd = action.get("command", "")
                yield {"event": "command_started", "data": {"command": cmd, "why": why}}
                r = self.sb.run(cmd, timeout=self.run_timeout, isolated=self.isolated)
                ran_any = True
                self.actions.append({"kind": "run", "command": cmd, "result": r})
                yield {"event": "command_finished", "data": {
                    "command": cmd, "exit_code": r.get("exit_code"),
                    "stdout": r.get("stdout", ""), "stderr": r.get("stderr", ""),
                    "blocked": r.get("blocked", False), "isolated": r.get("isolated", True)}}
            else:
                yield {"event": "agent_note", "data": {"text": f"unknown action: {act}"}}
        yield {"event": "code_done", "data": {"summary": "reached the step budget",
               "budget_hit": True, "steps": self.max_steps, "ran": ran_any}}
