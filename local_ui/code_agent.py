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
    "You are LOLM Code — an agentic coding system competing with Claude Code and Codex.\n"
    "Win by: (1) correct code that RUNS, (2) fixing real failures from REAL stdout/stderr, "
    "(3) multi-file projects when needed, (4) never claiming success without a green run.\n\n"
    "Sandbox: python3 + node + coreutils. Isolated Linux jail.\n"
    "HARD LIMITS (violations always fail):\n"
    "- NO network (no requests/urllib/fetch/APIs).\n"
    "- NO pip/npm install — stdlib only.\n"
    "- NO GUI (no pygame/tkinter/matplotlib windows).\n"
    "- NO interactive input() — use fixed sample values.\n"
    "- Must RUN AND EXIT in ~20s (no servers, no infinite loops).\n"
    "If the task needs network/GUI/server, ship a self-contained simulation that PRINTS results.\n\n"
    "Each turn reply in EXACTLY this format (you may emit MULTIPLE FILE blocks, then one RUN):\n"
    "FILE: <path>\n"
    "```\n"
    "<complete file contents>\n"
    "```\n"
    "FILE: <optional second path>\n"
    "```\n"
    "<contents>\n"
    "```\n"
    "RUN: <command>\n\n"
    "When the run fully satisfies the TASK (and any tests you added), reply ONLY:\n"
    "DONE: <one-line summary>\n\n"
    "Quality bar:\n"
    "- Prefer small pure functions + a main that prints clear results.\n"
    "- For non-trivial logic, add asserts or a tiny self-check in the same file and RUN it.\n"
    "- On failure: read the error, fix ROOT CAUSE, do not rewrite the same broken code.\n"
    "- Never DONE until you have SEEN exit 0 with meaningful printed output."
)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.S)
_FILE = re.compile(r"FILE\s*:\s*([\w./\-]{1,80})", re.IGNORECASE)
_RUN = re.compile(r"RUN\s*:\s*(.+)", re.IGNORECASE)
_DONE = re.compile(r"DONE\s*:\s*(.+)", re.IGNORECASE)
_FILE_BLOCK = re.compile(
    r"FILE\s*:\s*([\w./\-]{1,80})\s*\n```[a-zA-Z0-9_+\-]*\n(.*?)```",
    re.S | re.IGNORECASE,
)
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
    """Unified parser → files list + run + done.

    Returns:
      {"files": [(path, content), ...], "file": first|None, "run": cmd|None, "done": str|None}
    Multi-FILE turns are first-class (Claude Code / Codex parity for multi-file edits).
    """
    if not text or not text.strip():
        return None
    # legacy JSON action
    a = _extract_json(text)
    if a:
        act = a.get("action")
        if act == "write_file":
            pair = (a.get("path", "main.py"), a.get("content", ""))
            return {"files": [pair], "file": pair, "run": None, "done": None}
        if act == "run":
            return {"files": [], "file": None, "run": a.get("command"), "done": None}
        if act == "finish":
            return {"files": [], "file": None, "run": None, "done": a.get("summary", "done")}

    files = [(m.group(1), m.group(2)) for m in _FILE_BLOCK.finditer(text)]
    runm = _RUN.search(text)
    cmd = runm.group(1).strip().strip("`").strip() if runm else None

    if not files:
        fence = _FENCE.search(text)
        content = fence.group(1) if fence else None
        if content is not None or cmd is not None:
            name = None
            fm = _FILE.search(text)
            if fm:
                name = fm.group(1)
            if not name and content is not None:
                lang = re.search(r"```([a-zA-Z0-9_+\-]+)", text)
                name = "main." + _LANG_EXT.get((lang.group(1).lower() if lang else ""), "py")
            if content is not None:
                files = [(name, content)]

    if files or cmd is not None:
        first = files[0] if files else None
        return {"files": files, "file": first, "run": cmd, "done": None}

    dm = _DONE.search(text)
    if dm:
        return {"files": [], "file": None, "run": None, "done": dm.group(1).strip()}
    return None


def _wants_tests(task: str) -> bool:
    t = (task or "").lower()
    return any(k in t for k in (
        "test", "unittest", "pytest", "assert", "tdd", "spec", "verify",
    ))


def _is_test_path(path: str) -> bool:
    p = (path or "").replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in f"/{p}/"
        or p.startswith("tests/")
    )


def _pick_verify_command(files_written: List[str], task: str) -> Optional[str]:
    """Choose a post-green-run oracle. Prefer real tests over py_compile.

    Competitive bar vs Claude Code / Codex: if the agent wrote test files, run
    them (unittest discovery — always in stdlib; pytest when present). Otherwise
    for test-oriented or multi-file Python work, at least py_compile so we never
    DONE on syntax-broken trees.
    """
    py = [p for p in (files_written or []) if (p or "").endswith(".py")]
    if not py:
        return None
    tests = [p for p in py if _is_test_path(p)]
    if tests:
        # unittest discover is stdlib; try pytest first when installed in the jail.
        # Single shell line so sandbox.run stays one command.
        return (
            "python3 -c \"import importlib.util as u,sys; sys.exit(0 if u.find_spec('pytest') else 1)\" "
            "&& python3 -m pytest -q --tb=line "
            + " ".join(tests)
            + " || python3 -m unittest discover -s . -p 'test*.py' -q"
        )
    if _wants_tests(task) or len(py) >= 2:
        return "python3 -m py_compile " + " ".join(py)
    return None


class CodeAgent:
    def __init__(self, sandbox: Any, chat_fn: Callable[[List[Dict[str, str]]], str],
                 max_steps: int = 18, run_timeout: int = 25,
                 isolated: Optional[bool] = True):
        self.sb = sandbox
        self.chat = chat_fn
        self.max_steps = max_steps
        self.run_timeout = run_timeout
        self.isolated = isolated
        self.actions: List[Dict[str, Any]] = []
        self._format_nudge = ""
        self._files_written: List[str] = []

    def _context(self) -> str:
        if not self.actions:
            base = ("\n\n(Nothing run yet. Write the complete program and run it.\n"
                    "Reply EXACTLY:\nFILE: main.py\n```\n<code>\n```\nRUN: python3 main.py)")
            return base + (self._format_nudge or "")
        lines = ["\n\nSO FAR:"]
        for a in self.actions[-6:]:
            if a["kind"] == "write_file":
                lines.append(f"- wrote {a['path']} ({a.get('bytes', 0)} bytes)")
            else:
                r = a["result"]
                out = ((r.get("stdout") or "") + (r.get("stderr") or "")).strip()
                tag = "BLOCKED" if r.get("blocked") else f"exit {r.get('exit_code')}"
                lines.append(f"- ran `{a['command']}` → {tag}\n  OUTPUT: {out[:900] or '(empty)'}")
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
            lines.append("\nSend the next FILE + RUN (fix the program if the last run failed). "
                         "Do not invent success — use the real OUTPUT above.")
        if self._format_nudge:
            lines.append(self._format_nudge)
        return "\n".join(lines)

    def _auto_run_cmd(self, path: str) -> str:
        """Guess a run command when the model forgot RUN:."""
        p = (path or "main.py").lower()
        if p.endswith(".py"):
            return f"python3 {path}"
        if p.endswith(".js"):
            return f"node {path}"
        if p.endswith(".sh"):
            return f"bash {path}"
        return f"python3 {path}"

    def run(self, task: str) -> Iterator[Dict[str, Any]]:
        yield {"event": "code_start", "data": {"task": task, "sandbox": self.sb.id}}
        ran_any = False
        produced_output = False
        nudges = 0
        fail_sig = None
        fail_repeats = 0
        parse_fails = 0
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
                parse_fails += 1
                self._format_nudge = (
                    "\n\nFORMAT ERROR: Your last reply was not parseable. Reply with ONLY:\n"
                    "FILE: main.py\n```\n# full program\n```\nRUN: python3 main.py\n"
                    "No prose outside that format."
                )
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "could not parse reply — re-prompting with format fix",
                       "raw": (raw or "")[:300]}}
                if parse_fails >= 3:
                    yield {"event": "code_done", "data": {
                        "summary": "Model kept ignoring FILE/RUN format after 3 tries.",
                        "budget_hit": True, "steps": step, "ran": ran_any,
                        "produced_output": produced_output}}
                    return
                continue
            parse_fails = 0
            self._format_nudge = ""

            # pure DONE → finish (gated on a real, output-producing run)
            if turn["done"] and not turn["file"] and not turn["run"]:
                if not ran_any and nudges < 2:
                    nudges += 1
                    self._format_nudge = "\n\nYou must FILE + RUN before DONE."
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish without running the code — making it run first"}}
                    continue
                if ran_any and not produced_output and nudges < 3:
                    nudges += 1
                    self._format_nudge = "\n\nLast run printed nothing. Fix the program so it PRINTS."
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish but nothing was printed — making it produce output"}}
                    continue
                # Gate DONE on test oracle when test files exist (Claude/Codex parity).
                vcmd = _pick_verify_command(self._files_written, task)
                if vcmd and any(_is_test_path(p) for p in self._files_written) and nudges < 4:
                    note = vcmd if len(vcmd) <= 140 else vcmd[:137] + "…"
                    yield {"event": "agent_note", "data": {
                        "text": f"pre-DONE verify: `{note}`"}}
                    yield {"event": "command_started", "data": {"command": vcmd}}
                    vr = self.sb.run(vcmd, timeout=self.run_timeout, isolated=self.isolated)
                    self.actions.append({"kind": "run", "command": vcmd, "result": vr})
                    yield {"event": "command_finished", "data": {
                        "command": vcmd, "exit_code": vr.get("exit_code"),
                        "stdout": vr.get("stdout", ""), "stderr": vr.get("stderr", ""),
                        "blocked": vr.get("blocked", False), "isolated": True,
                        "verify": True}}
                    if vr.get("exit_code") != 0 or vr.get("blocked"):
                        nudges += 1
                        self._format_nudge = (
                            "\n\nTESTS FAILED before DONE. Fix the failing tests, FILE + RUN again. "
                            "Do not say DONE until tests pass."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "blocked DONE — tests still failing"}}
                        continue
                yield {"event": "code_done", "data": {"summary": turn["done"], "steps": step,
                       "ran": ran_any, "produced_output": produced_output}}
                return

            did = False
            written_path = None
            file_list = turn.get("files") or (
                [turn["file"]] if turn.get("file") and turn["file"][1] is not None else []
            )
            for path, content in file_list:
                if content is None:
                    continue
                written_path = path
                try:
                    fc = self.sb.write_file(path, content, reason="")
                    self.actions.append({"kind": "write_file", "path": path, "bytes": len(content)})
                    if path not in self._files_written:
                        self._files_written.append(path)
                    yield {"event": "file_changed", "data": {"path": path,
                           "diff": (fc.get("diff") or "")[:2500], "bytes": len(content)}}
                    did = True
                except Exception as exc:
                    yield {"event": "agent_note", "data": {"text": f"write failed: {exc}"[:160]}}
            # If model wrote a file but forgot RUN, auto-run once.
            cmd = turn["run"]
            if not cmd and written_path and did:
                cmd = self._auto_run_cmd(written_path)
                yield {"event": "agent_note", "data": {
                    "text": f"no RUN line — auto-running `{cmd}`"}}
            if cmd:
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
                    # Competitive bar: after a green run, prefer a real test oracle
                    # (pytest/unittest) when test files exist; else py_compile on
                    # multi-file / test-oriented tasks so we never DONE on garbage.
                    if ok and produced_output:
                        vcmd = _pick_verify_command(self._files_written, task)
                        if vcmd:
                            # Avoid re-running the exact same verify after every green
                            # run in a flail loop — only once per unique command set.
                            last_v = next(
                                (a for a in reversed(self.actions)
                                 if a.get("kind") == "run" and a.get("command") == vcmd),
                                None,
                            )
                            if last_v and last_v.get("result", {}).get("exit_code") == 0:
                                pass  # already verified cleanly
                            else:
                                note = vcmd if len(vcmd) < 140 else vcmd[:137] + "…"
                                yield {"event": "agent_note", "data": {
                                    "text": f"verify: `{note}`"}}
                                yield {"event": "command_started", "data": {"command": vcmd}}
                                vr = self.sb.run(vcmd, timeout=self.run_timeout,
                                                 isolated=self.isolated)
                                self.actions.append({"kind": "run", "command": vcmd, "result": vr})
                                yield {"event": "command_finished", "data": {
                                    "command": vcmd, "exit_code": vr.get("exit_code"),
                                    "stdout": vr.get("stdout", ""), "stderr": vr.get("stderr", ""),
                                    "blocked": vr.get("blocked", False), "isolated": True,
                                    "verify": True}}
                                if vr.get("exit_code") != 0 or vr.get("blocked"):
                                    ok = False
                                    produced_output = True  # keep working
                                    self._format_nudge = (
                                        "\n\nVERIFY FAILED. Fix syntax/tests, then RUN again. "
                                        "Do not say DONE."
                                    )
            if not did:
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "no FILE or RUN in the reply", "raw": (raw or "")[:200]}}
                self._format_nudge = (
                    "\n\nYou must include FILE: + fenced code + RUN: on every turn until DONE."
                )
        yield {"event": "code_done", "data": {"summary": "reached the step budget",
               "budget_hit": True, "steps": self.max_steps, "ran": ran_any,
               "produced_output": produced_output}}
