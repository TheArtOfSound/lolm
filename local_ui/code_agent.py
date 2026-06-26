# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Agentic coding loop — the agent writes code, runs it, reads the failure, fixes it.

The "Claude Code" inner loop on LOLM's isolated sandbox. Each turn the model emits a
COMPLETE file (as a fenced code block — the format LLMs are actually reliable at, unlike
escaping a whole program inside a JSON string) plus a RUN command, or DONE. The loop
writes + runs it for real in the bwrap jail, feeds the actual stdout/exit back, and
iterates until the program runs AND prints the expected output. Everything is real and
recorded — the model only proposes; the loop is the sole thing that touches the sandbox.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterator, List, Optional

SYSTEM = (
    "You are a precise coding agent in a SANDBOXED Linux box. python3 and node are "
    "available. Solve the TASK by writing a COMPLETE, RUNNABLE program that performs the "
    "task AND prints its results.\n\n"
    "ENVIRONMENT LIMITS — code that violates these WILL FAIL, so design around them:\n"
    "- NO network (requests/urllib/fetch/scraping/APIs all fail — never use them).\n"
    "- NO pip/npm install — standard library only.\n"
    "- NO GUI/display (no pygame/tkinter/turtle/matplotlib windows).\n"
    "- NO interactive input — input()/readline BLOCKS FOREVER. Use fixed sample values.\n"
    "- The program must RUN AND EXIT in ~15s: no servers, no infinite loops, no waiting.\n"
    "If the task as literally asked needs the network, a GUI, a server, or live typing, "
    "write a SELF-CONTAINED version that demonstrates the core logic with sample/hard-coded "
    "data and PRINTS the result (e.g. simulate a few game turns and print each board; parse "
    "a hard-coded HTML string instead of fetching a URL; drive a calculator with example "
    "inputs). Print one line noting what you substituted.\n\n"
    "Reply in EXACTLY this format each turn (nothing else):\n"
    "FILE: <filename>\n"
    "```\n"
    "<the complete file contents>\n"
    "```\n"
    "RUN: <command to run it>\n\n"
    "When the run output correctly satisfies the TASK, reply with exactly one line:\n"
    "DONE: <one-line summary>\n\n"
    "Rules: the FILE must be the WHOLE program and must PRINT results. After each run you "
    "see the REAL output; if it failed, FIX THE ROOT CAUSE (don't repeat the same code). "
    "Never say DONE until you have SEEN a successful run with the expected output."
)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.S)
_FILE = re.compile(r"FILE\s*:\s*([\w./\-]{1,80})", re.IGNORECASE)
_RUN = re.compile(r"RUN\s*:\s*(.+)", re.IGNORECASE)
_DONE = re.compile(r"DONE\s*:\s*(.+)", re.IGNORECASE)
_LANG_EXT = {"python": "py", "py": "py", "python3": "py", "javascript": "js", "js": "js",
             "node": "js", "bash": "sh", "sh": "sh", "shell": "sh", "go": "go"}


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull a JSON action object out of a reply (legacy/strict format)."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict) and obj.get("action"):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _parse_turn(text: str) -> Optional[Dict[str, Any]]:
    """Unified parser → {"file": (name, content)|None, "run": cmd|None, "done": str|None}.
    Accepts the natural FILE/```/RUN/DONE format AND the legacy JSON action format. A turn
    that writes/runs is executed; a pure DONE finishes."""
    if not text or not text.strip():
        return None
    # legacy JSON action
    a = _extract_json(text)
    if a:
        act = a.get("action")
        if act == "write_file":
            return {"file": (a.get("path", "main.py"), a.get("content", "")), "run": None, "done": None}
        if act == "run":
            return {"file": None, "run": a.get("command"), "done": None}
        if act == "finish":
            return {"file": None, "run": None, "done": a.get("summary", "done")}

    fence = _FENCE.search(text)
    runm = _RUN.search(text)
    content = fence.group(1) if fence else None
    cmd = runm.group(1).strip().strip("`").strip() if runm else None

    if content is not None or cmd is not None:
        name = None
        fm = _FILE.search(text)
        if fm:
            name = fm.group(1)
        if not name and content is not None:
            lang = re.search(r"```([a-zA-Z0-9_+\-]+)", text)
            name = "main." + _LANG_EXT.get((lang.group(1).lower() if lang else ""), "py")
        return {"file": (name, content) if content is not None else None,
                "run": cmd, "done": None}

    dm = _DONE.search(text)
    if dm:
        return {"file": None, "run": None, "done": dm.group(1).strip()}
    return None


class CodeAgent:
    def __init__(self, sandbox: Any, chat_fn: Callable[[List[Dict[str, str]]], str],
                 max_steps: int = 8, run_timeout: int = 15,
                 isolated: Optional[bool] = True):
        self.sb = sandbox
        self.chat = chat_fn
        self.max_steps = max_steps
        self.run_timeout = run_timeout
        self.isolated = isolated
        self.actions: List[Dict[str, Any]] = []

    def _context(self) -> str:
        if not self.actions:
            return "\n\n(Nothing run yet. Write the complete program and run it.)"
        lines = ["\n\nSO FAR:"]
        for a in self.actions[-5:]:
            if a["kind"] == "write_file":
                lines.append(f"- wrote {a['path']} ({a.get('bytes', 0)} bytes)")
            else:
                r = a["result"]
                out = ((r.get("stdout") or "") + (r.get("stderr") or "")).strip()
                tag = "BLOCKED" if r.get("blocked") else f"exit {r.get('exit_code')}"
                lines.append(f"- ran `{a['command']}` → {tag}\n  OUTPUT: {out[:700] or '(empty)'}")
        last = self.actions[-1]
        if last["kind"] == "run" and not last["result"].get("blocked") \
                and last["result"].get("exit_code") == 0:
            if (last["result"].get("stdout") or "").strip():
                lines.append("\nThe last run printed the output above. If it satisfies the "
                             "TASK, reply `DONE: ...`. Otherwise send a corrected FILE + RUN.")
            else:
                lines.append("\nThe last run exited 0 but printed NOTHING. Rewrite the FULL "
                             "program so it actually runs the logic and PRINTS results, with "
                             "a RUN line. Do NOT say DONE.")
        else:
            lines.append("\nSend the next FILE + RUN (fix the program if the last run failed).")
        return "\n".join(lines)

    def run(self, task: str) -> Iterator[Dict[str, Any]]:
        yield {"event": "code_start", "data": {"task": task, "sandbox": self.sb.id}}
        ran_any = False
        produced_output = False
        nudges = 0
        fail_sig = None
        fail_repeats = 0
        for step in range(self.max_steps):
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"TASK: {task}{self._context()}"}]
            yield {"event": "code_thinking", "data": {"step": step, "of": self.max_steps,
                   "ran": ran_any}}
            try:
                raw = self.chat(msgs)
            except Exception as exc:
                yield {"event": "error", "data": {"error": f"model failed: {exc}"[:200]}}
                return
            turn = _parse_turn(raw)
            if turn is None:
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "could not parse the model's reply into a FILE/RUN action",
                       "raw": (raw or "")[:300]}}
                break

            # pure DONE → finish (gated on a real, output-producing run)
            if turn["done"] and not turn["file"] and not turn["run"]:
                if not ran_any and nudges < 2:
                    nudges += 1
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish without running the code — making it run first"}}
                    continue
                if ran_any and not produced_output and nudges < 3:
                    nudges += 1
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish but nothing was printed — making it produce output"}}
                    continue
                yield {"event": "code_done", "data": {"summary": turn["done"], "steps": step,
                       "ran": ran_any, "produced_output": produced_output}}
                return

            did = False
            if turn["file"] and turn["file"][1] is not None:
                path, content = turn["file"]
                try:
                    fc = self.sb.write_file(path, content, reason="")
                    self.actions.append({"kind": "write_file", "path": path, "bytes": len(content)})
                    yield {"event": "file_changed", "data": {"path": path,
                           "diff": (fc.get("diff") or "")[:2500], "bytes": len(content)}}
                    did = True
                except Exception as exc:
                    yield {"event": "agent_note", "data": {"text": f"write failed: {exc}"[:160]}}
            if turn["run"]:
                cmd = turn["run"]
                yield {"event": "command_started", "data": {"command": cmd}}
                r = self.sb.run(cmd, timeout=self.run_timeout, isolated=self.isolated)
                ran_any = True
                ok = r.get("exit_code") == 0 and not r.get("blocked")
                if ok and (r.get("stdout") or "").strip():
                    produced_output = True
                self.actions.append({"kind": "run", "command": cmd, "result": r})
                yield {"event": "command_finished", "data": {
                    "command": cmd, "exit_code": r.get("exit_code"),
                    "stdout": r.get("stdout", ""), "stderr": r.get("stderr", ""),
                    "blocked": r.get("blocked", False), "isolated": r.get("isolated", True)}}
                did = True
                # Flail guard: if the same failure repeats, stop and report honestly
                # instead of burning every step on identical errors.
                if not ok:
                    err = (r.get("stderr") or "").strip().splitlines()
                    sig = (err[-1][:90] if err else "fail")
                    fail_repeats = fail_repeats + 1 if sig == fail_sig else 0
                    fail_sig = sig
                    if fail_repeats >= 2:
                        yield {"event": "code_done", "data": {
                            "summary": ("Couldn't get a clean run in the sandbox — the same error "
                                        "kept recurring. This task likely needs the network, a GUI, "
                                        "a server, or live input, which the isolated sandbox doesn't "
                                        "have. The code is written above."),
                            "ran": ran_any, "produced_output": produced_output, "stuck": True,
                            "steps": step}}
                        return
                else:
                    fail_repeats = 0
                    fail_sig = None
            if not did:
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "no FILE or RUN in the reply", "raw": (raw or "")[:200]}}
        yield {"event": "code_done", "data": {"summary": "reached the step budget",
               "budget_hit": True, "steps": self.max_steps, "ran": ran_any,
               "produced_output": produced_output}}
