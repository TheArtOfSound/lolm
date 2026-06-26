# Copyright (c) 2026 Qira LLC. All rights reserved.
"""LOLM Operator — a general multi-tool agent over the sandbox "virtual PC".

Where code_agent only writes+runs one program, the Operator pursues a GOAL with a
full toolset against a persistent sandboxed workspace: list/read/write/edit files,
run shell commands in the bwrap jail, and search the web (read-only). It loops
plan -> act -> observe -> verify until the goal is done or the step budget is hit,
streaming every tool call and its REAL result.

The model proposes exactly ONE action per step in a simple line/fence protocol; the
loop is the only thing that touches the sandbox, so an untrusted model can't escape
the jail. This is "Claude Code in LOLM's own virtual machine" — with the difference
that every action is recorded into a receipt and (on the owner path) gated by the
operator's measured uncertainty.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterator, List, Optional


SYSTEM = (
    "You are LOLM Operator: an autonomous agent with your own VIRTUAL COMPUTER — a "
    "sandboxed Linux workspace with a real filesystem and shell. Achieve the GOAL by "
    "taking ONE action per step. After each action you see its REAL result, then you "
    "take the next action. Work methodically: inspect, plan, build, run, verify, fix.\n\n"
    "Each step, reply in EXACTLY this shape (a one-line plan, then ONE action):\n"
    "STEP: <what you're doing and why, one line>\n"
    "<ACTION>\n\n"
    "ACTION is exactly ONE of:\n"
    "  LIST                         — list files in the workspace\n"
    "  READ: <path>                 — print a file's contents\n"
    "  WRITE: <path>                — create/overwrite a file; put the FULL contents in a\n"
    "  ```\n  <file contents>\n  ```  fenced block on the next lines\n"
    "  RUN: <shell command>         — run a command (python3/node/pip-free, must exit)\n"
    "  SEARCH: <query>              — search the web (read-only) for facts/docs\n"
    "  DONE: <one-line summary>     — the goal is fully achieved and VERIFIED\n\n"
    "ENVIRONMENT LIMITS: no network except SEARCH; no GUI; no interactive stdin; the "
    "jail has python3 + node + coreutils, stdlib only (no pip/npm install); commands must "
    "run and EXIT (no servers/infinite loops). Build self-contained things.\n"
    "RULES: take only ONE action per step. Before WRITE, prefer LIST/READ to know the "
    "state. Always RUN code to verify it works before DONE — never claim success you "
    "haven't seen. If a command fails, READ the error and fix the root cause."
)

_FENCE = re.compile(r"```[a-zA-Z0-9_]*\n?(.*?)```", re.DOTALL)


def _parse_action(text: str) -> Optional[Dict[str, Any]]:
    """Pull ONE action out of the model's reply. Priority handles replies that
    accidentally include several keywords: real actions beat a trailing DONE."""
    if not text:
        return None
    step = ""
    m = re.search(r"^\s*STEP:\s*(.+)$", text, re.MULTILINE)
    if m:
        step = m.group(1).strip()[:200]

    # WRITE: <path> + a fenced block of contents
    mw = re.search(r"^\s*WRITE:\s*(\S+)", text, re.MULTILINE)
    if mw:
        fence = _FENCE.search(text)
        if fence:
            return {"tool": "write", "path": mw.group(1).strip().strip('"`'),
                    "content": fence.group(1), "step": step}

    mr = re.search(r"^\s*RUN:\s*(.+)$", text, re.MULTILINE)
    if mr:
        return {"tool": "run", "command": mr.group(1).strip().strip("`"), "step": step}

    mrd = re.search(r"^\s*READ:\s*(\S+)", text, re.MULTILINE)
    if mrd:
        return {"tool": "read", "path": mrd.group(1).strip().strip('"`'), "step": step}

    ms = re.search(r"^\s*SEARCH:\s*(.+)$", text, re.MULTILINE)
    if ms:
        return {"tool": "search", "query": ms.group(1).strip(), "step": step}

    if re.search(r"^\s*LIST\s*$", text, re.MULTILINE):
        return {"tool": "list", "step": step}

    md = re.search(r"^\s*DONE:\s*(.+)$", text, re.MULTILINE | re.DOTALL)
    if md:
        return {"tool": "done", "summary": md.group(1).strip()[:400], "step": step}
    return None


class AgentOperator:
    def __init__(self, sandbox: Any,
                 chat_fn: Callable[[List[Dict[str, str]]], str],
                 search_fn: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
                 max_steps: int = 14, run_timeout: int = 20,
                 isolated: Optional[bool] = True):
        self.sb = sandbox
        self.chat = chat_fn
        self.search = search_fn
        self.max_steps = max_steps
        self.run_timeout = run_timeout
        self.isolated = isolated
        self.log: List[Dict[str, Any]] = []        # full action/result receipt

    def _context(self) -> str:
        if not self.log:
            files = self.sb.list_files(limit=40)
            cur = ("\n".join(files) if files else "(empty workspace)")
            return f"\n\nWORKSPACE FILES:\n{cur}\n\nTake your first action."
        lines = ["\n\nWHAT YOU'VE DONE (most recent last):"]
        for a in self.log[-6:]:
            lines.append(f"- {a['kind']}: {a['summary']}")
        last = self.log[-1]
        if last.get("observation"):
            lines.append(f"\nLAST RESULT:\n{last['observation'][:1400]}")
        # Convergence: don't let it re-run already-working commands forever. Once
        # something has run cleanly, steer hard toward DONE.
        run_cmds = [a["summary"] for a in self.log if a["kind"] == "run"]
        ok_runs = [a for a in self.log if a["kind"] == "run" and "-> exit 0" in a["summary"]]
        repeated = len(run_cmds) != len(set(run_cmds))
        if last["kind"] == "run" and "-> exit 0" in last["summary"]:
            lines.append("\n✓ Your last command SUCCEEDED. If the GOAL is now achieved, reply "
                         "`DONE: <summary>` THIS step. Do NOT re-run a command that already "
                         "worked — that wastes steps.")
        elif repeated or len(ok_runs) >= 2:
            lines.append("\nYou have already run things successfully — STOP repeating commands. "
                         "If the GOAL is met, reply `DONE: <summary>` now; otherwise take the ONE "
                         "remaining new action needed.")
        else:
            lines.append("\nTake the next single action (or `DONE: <summary>` if the goal is "
                         "verified).")
        return "\n".join(lines)

    def run(self, goal: str) -> Iterator[Dict[str, Any]]:
        yield {"event": "operator_start", "data": {"goal": goal, "sandbox": self.sb.id,
               "tools": ["list", "read", "write", "run", "search", "done"]}}
        ran_something = False
        nudges = 0
        for step in range(self.max_steps):
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"GOAL: {goal}{self._context()}"}]
            yield {"event": "operator_thinking", "data": {"step": step, "of": self.max_steps}}
            try:
                raw = self.chat(msgs)
            except Exception as exc:
                yield {"event": "error", "data": {"error": f"model failed: {exc}"[:200]}}
                return
            act = _parse_action(raw)
            if act is None:
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "couldn't parse an action — re-prompting",
                       "raw": (raw or "")[:240]}}
                continue
            if act.get("step"):
                yield {"event": "operator_step", "data": {"step": step, "plan": act["step"],
                       "tool": act["tool"]}}

            tool = act["tool"]
            # ── DONE (gated on having actually run/verified something) ──
            if tool == "done":
                if not ran_something and nudges < 2:
                    nudges += 1
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish without running/verifying — keep going"}}
                    self.log.append({"kind": "note", "summary": "premature DONE — nudged",
                                     "observation": "You haven't RUN anything yet. Build it and "
                                                    "RUN it to verify before DONE."})
                    continue
                yield {"event": "operator_done", "data": {"summary": act["summary"],
                       "steps": step, "actions": len(self.log), "verified": ran_something}}
                return

            # ── LIST ──
            if tool == "list":
                files = self.sb.list_files(limit=300)
                obs = "\n".join(files) if files else "(empty)"
                yield {"event": "tool_call", "data": {"tool": "list", "files": files}}
                self.log.append({"kind": "list", "summary": f"listed {len(files)} files",
                                 "observation": obs})
                continue

            # ── READ ──
            if tool == "read":
                try:
                    content = self.sb.read_file(act["path"])
                    obs = content[:4000]
                    yield {"event": "tool_call", "data": {"tool": "read", "path": act["path"]}}
                    yield {"event": "file_view", "data": {"path": act["path"], "content": obs}}
                    self.log.append({"kind": "read", "summary": f"read {act['path']}",
                                     "observation": obs})
                except Exception as exc:
                    self.log.append({"kind": "read", "summary": f"read {act['path']} failed",
                                     "observation": f"error: {exc}"[:300]})
                    yield {"event": "agent_note", "data": {"text": f"read failed: {exc}"[:160]}}
                continue

            # ── WRITE ──
            if tool == "write":
                try:
                    fc = self.sb.write_file(act["path"], act["content"], reason="operator")
                    yield {"event": "tool_call", "data": {"tool": "write", "path": act["path"]}}
                    yield {"event": "file_changed", "data": {"path": act["path"],
                           "diff": (fc.get("diff") or "")[:2500],
                           "bytes": len(act["content"])}}
                    self.log.append({"kind": "write",
                                     "summary": f"wrote {act['path']} ({len(act['content'])} bytes)",
                                     "observation": f"wrote {act['path']}"})
                except Exception as exc:
                    self.log.append({"kind": "write", "summary": f"write {act['path']} failed",
                                     "observation": f"error: {exc}"[:300]})
                    yield {"event": "agent_note", "data": {"text": f"write failed: {exc}"[:160]}}
                continue

            # ── RUN ──
            if tool == "run":
                cmd = act["command"]
                yield {"event": "command_started", "data": {"command": cmd}}
                r = self.sb.run(cmd, timeout=self.run_timeout, isolated=self.isolated)
                ran_something = True
                out = ((r.get("stdout") or "") + (r.get("stderr") or "")).strip()
                yield {"event": "command_finished", "data": {
                    "command": cmd, "exit_code": r.get("exit_code"),
                    "stdout": r.get("stdout", ""), "stderr": r.get("stderr", ""),
                    "blocked": r.get("blocked", False), "isolated": r.get("isolated", True)}}
                tag = "BLOCKED" if r.get("blocked") else f"exit {r.get('exit_code')}"
                self.log.append({"kind": "run", "summary": f"ran `{cmd}` -> {tag}",
                                 "observation": f"$ {cmd}\n{tag}\n{out[:1300] or '(no output)'}"})
                continue

            # ── SEARCH (read-only) ──
            if tool == "search":
                q = act["query"]
                results = []
                if self.search is not None:
                    try:
                        results = self.search(q) or []
                    except Exception:
                        results = []
                yield {"event": "web_result", "data": {"query": q, "results": results[:5]}}
                obs = ("\n".join(f"- {x.get('title','')}: {x.get('snippet') or x.get('url','')}"
                                 for x in results[:5]) or "(no results)")
                self.log.append({"kind": "search", "summary": f"searched: {q}",
                                 "observation": obs})
                continue

        yield {"event": "operator_done", "data": {"summary": "reached the step budget",
               "budget_hit": True, "steps": self.max_steps, "actions": len(self.log),
               "verified": ran_something}}
