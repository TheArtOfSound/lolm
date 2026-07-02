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
    "Each step, reply in EXACTLY this shape (a SHORT plan, then ONE action):\n"
    "STEP: <a short phrase, max ~10 words>\n"
    "<ACTION>\n\n"
    "CRITICAL: keep STEP to ONE short phrase and put the ACTION right after it. Do NOT "
    "write long explanations before the action — a long plan gets cut off before the "
    "action block and wastes the whole step. The ACTION (especially the file contents) is "
    "what matters; spend your words there, not on the plan.\n\n"
    "ACTION is exactly ONE of:\n"
    "  LIST                         — list files in the workspace\n"
    "  READ: <path>                 — print a file's contents\n"
    "  WRITE: <path>                — create/overwrite a file; put the FULL contents in a\n"
    "  ```\n  <file contents>\n  ```  fenced block on the next lines\n"
    "  EDIT: <path>                 — change PART of an existing file with a search/replace\n"
    "      block (exact existing text -> new text), on the lines right after:\n"
    "      <<<<<<< SEARCH\n      <exact existing lines to find>\n      =======\n"
    "      <replacement lines>\n      >>>>>>> REPLACE\n"
    "  RUN: <shell command>         — run a command (python3/node/pip-free, must exit)\n"
    "  SEARCH: <query>              — search the web (read-only) for facts/docs/URLs\n"
    "  FETCH: <url>                 — read the FULL text of a web page (read-only)\n"
    "  DONE: <one-line summary>     — the goal is fully achieved and VERIFIED\n\n"
    "ENVIRONMENT LIMITS: network is READ-ONLY and only via SEARCH and FETCH; no GUI; no "
    "interactive stdin; the jail has python3 + node + coreutils, stdlib only (no pip/npm "
    "install); commands must run and EXIT (no servers/infinite loops). Build self-contained "
    "things.\n"
    "RULES: take only ONE action per step. Before WRITE/EDIT, prefer LIST/READ to know the "
    "state. For a small change to an existing file use EDIT (cheaper and safer than rewriting "
    "it whole); use WRITE for new files or full rewrites. To use the web, SEARCH for a URL "
    "then FETCH it for the full content. Always RUN code to verify it works before DONE — "
    "never claim success you haven't seen. If a command fails, READ the error and fix the "
    "root cause."
)

_FENCE = re.compile(r"```[a-zA-Z0-9_]*\n?(.*?)```", re.DOTALL)
_SR = re.compile(r"<<<<<<<\s*SEARCH\s*\n(.*?)\n?=======\s*\n(.*?)\n?>>>>>>>\s*REPLACE", re.DOTALL)


def _parse_action(text: str) -> Optional[Dict[str, Any]]:
    """Pull ONE action out of the model's reply. Priority handles replies that
    accidentally include several keywords: real actions beat a trailing DONE."""
    if not text:
        return None
    step = ""
    m = re.search(r"^\s*STEP:\s*(.+)$", text, re.MULTILINE)
    if m:
        step = m.group(1).strip()[:200]

    # EDIT: <path> + a SEARCH/REPLACE block (checked before WRITE — both touch files)
    me = re.search(r"^\s*EDIT:\s*(\S+)", text, re.MULTILINE)
    if me:
        blk = _SR.search(text)
        if blk:
            return {"tool": "edit", "path": me.group(1).strip().strip('"`'),
                    "old": blk.group(1), "new": blk.group(2), "step": step}

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

    mf = re.search(r"^\s*FETCH:\s*(\S+)", text, re.MULTILINE)
    if mf:
        return {"tool": "fetch", "url": mf.group(1).strip().strip('"`<>'), "step": step}

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

    # Tolerant fallback: models frequently emit a fenced code block and NAME the
    # target file in their STEP/prose but forget the exact `WRITE: <path>` header.
    # Rather than waste the step on a parse failure, infer a WRITE when we can see
    # BOTH a non-empty fence and a filename. (Only as a last resort — every explicit
    # action tag above wins first.)
    fence = _FENCE.search(text)
    if fence and fence.group(1).strip():
        # look for the filename in the STEP/prose BEFORE the fence — never inside the
        # code itself (which may mention incidental paths like open("data.json")).
        pre = step + "\n" + text[:fence.start()]
        fn = re.search(r"\b([\w./-]+\.(?:py|js|ts|html?|css|json|md|txt|sh|c|cpp|cc|h|hpp"
                       r"|java|go|rs|rb|php|sql|ya?ml|toml|ini))\b", pre)
        if fn:
            return {"tool": "write", "path": fn.group(1).strip().strip('"`'),
                    "content": fence.group(1), "step": step}
    return None


class AgentOperator:
    def __init__(self, sandbox: Any,
                 chat_fn: Callable[[List[Dict[str, str]]], str],
                 search_fn: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
                 fetch_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
                 max_steps: int = 14, run_timeout: int = 20,
                 isolated: Optional[bool] = True):
        self.sb = sandbox
        self.chat = chat_fn
        self.search = search_fn
        self.fetch = fetch_fn
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
        # Anti-stall: a real failure mode is re-READING a file over and over to
        # "analyze the bug" without ever committing to a fix. Reading again reveals
        # nothing new — force an EDIT/WRITE then a RUN.
        recent = self.log[-3:]
        recent_reads = sum(1 for a in recent if a["kind"] == "read")
        acted_recently = any(a["kind"] in ("write", "edit", "run") for a in recent)
        if last["kind"] == "run" and "-> exit 0" in last["summary"]:
            lines.append("\n✓ Your last command ran with exit 0 — its output is shown above. "
                         "COMPARE that output to the GOAL. If it matches, reply `DONE: <summary>` "
                         "THIS step — a debug/build goal is finished the MOMENT a run shows the "
                         "correct result; do not keep reading or re-running something that already "
                         "works. Only keep going if the output still does NOT meet the goal.")
        elif last.get("changed"):        # only after a write/edit that ACTUALLY landed
            lines.append("\n✓ You just changed a file. RUN it NOW to see whether it works — do "
                         "NOT read it first, `RUN:` it. Verifying a change means executing it, "
                         "not re-reading it.")
        elif recent_reads >= 2 and not acted_recently:
            lines.append("\n⚠ You have READ the file(s) repeatedly WITHOUT changing anything. "
                         "Reading again reveals nothing new — you already have what you need. If "
                         "there is a bug, make the ONE `EDIT:` that fixes it THIS step (or "
                         "`WRITE:` the whole corrected file), then `RUN:` it to prove the fix. Do "
                         "NOT read the same file again.")
        elif repeated or len(ok_runs) >= 2:
            lines.append("\nYou have already run things successfully — STOP repeating commands. "
                         "If the GOAL is met, reply `DONE: <summary>` now; otherwise take the ONE "
                         "remaining new action needed.")
        else:
            lines.append("\nTake the next single action (or `DONE: <summary>` if the goal is "
                         "verified).")
        return "\n".join(lines)

    def _verify_goal(self, goal: str) -> Dict[str, Any]:
        """Independent, skeptical OUTCOME check — the Hellhound discipline: DONE
        must be EARNED, not asserted. A separate strict verifier reviews the goal
        against what was actually done and the REAL command output, and defaults
        to failure unless success is proven. Returns {verified, reason}. This is
        what makes the receipt's `verified` flag honest instead of "ran anything".
        """
        transcript = [f"- {a['kind']}: {a['summary']}" for a in self.log[-10:]]
        last_out = ""
        for a in reversed(self.log):
            if a["kind"] == "run":
                last_out = (a.get("observation") or "")[:1200]
                break
        system = (
            "You are a STRICT verifier auditing whether an agent TRULY achieved a goal. "
            "Be skeptical: assume it FAILED unless the evidence clearly proves success. "
            "Judge ONLY from the actions taken and the actual command output — never from "
            "what the agent claims. A goal that needs code is met only if a run exited 0 "
            "AND its output shows the intended behavior. IMPORTANT: judge by the FINAL / "
            "MOST-RECENT run output below — a debug or build task legitimately has earlier "
            "FAILED attempts before it works, and those earlier failures do NOT count against "
            "it if the latest run now shows the correct result. Reply with EXACTLY one line:\n"
            "`VERIFIED: <one-line why>` if the latest run proves the goal is met, or\n"
            "`NOT_VERIFIED: <what is still wrong in the latest run>` otherwise.")
        user = (f"GOAL:\n{goal}\n\nACTIONS TAKEN:\n" + ("\n".join(transcript) or "(none)") +
                f"\n\nMOST RECENT RUN OUTPUT:\n{last_out or '(nothing was ever run)'}\n\nVerdict:")
        try:
            raw = (self.chat([{"role": "system", "content": system},
                              {"role": "user", "content": user}]) or "").strip()
        except Exception as exc:
            return {"verified": False, "reason": f"verifier unavailable: {exc}"[:140], "raw": ""}
        up = raw.upper()
        verified = ("NOT_VERIFIED" not in up) and ("NOT VERIFIED" not in up) and ("VERIFIED" in up)
        reason = raw.split(":", 1)[1].strip()[:220] if ":" in raw else raw[:220]
        return {"verified": bool(verified), "reason": reason or raw[:220], "raw": raw[:280]}

    def run(self, goal: str) -> Iterator[Dict[str, Any]]:
        yield {"event": "operator_start", "data": {"goal": goal, "sandbox": self.sb.id,
               "tools": ["list", "read", "write", "edit", "run", "search", "fetch", "done"]}}
        ran_something = False
        clean_runs = 0            # runs that exited 0 (honest success count)
        verify_fails = 0          # times the strict verifier rejected a DONE
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
                # A reply with a plan but no runnable action (often a verbose STEP that
                # got cut off before the action). Leave a crisp format reminder so the
                # next turn emits a REAL action, not more prose.
                self.log.append({"kind": "note", "summary": "no action parsed",
                                 "observation": "Your last reply had NO runnable action — only a "
                                 "plan/prose. Emit ONE action block NOW, action FIRST, e.g.:\n"
                                 "WRITE: <path>\n```\n<full file contents>\n```\n"
                                 "or `RUN: <command>`. Do NOT describe it — EMIT it, and keep any "
                                 "STEP line to a few words so it isn't cut off."})
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "no action parsed — sent the exact format to use",
                       "raw": (raw or "")[:240]}}
                continue
            if act.get("step"):
                yield {"event": "operator_step", "data": {"step": step, "plan": act["step"],
                       "tool": act["tool"]}}

            tool = act["tool"]
            # ── DONE (EARNED: gated on an independent strict verifier, not the
            #    model's say-so, and not merely "ran anything") ──
            if tool == "done":
                if not ran_something and nudges < 2:
                    nudges += 1
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish without running/verifying — keep going"}}
                    self.log.append({"kind": "note", "summary": "premature DONE — nudged",
                                     "observation": "You haven't RUN anything yet. Build it and "
                                                    "RUN it to verify before DONE."})
                    continue
                yield {"event": "verifying", "data": {"step": step}}
                verdict = self._verify_goal(goal)
                yield {"event": "verification", "data": {"verified": verdict["verified"],
                       "reason": verdict["reason"]}}
                # A rejected finish is sent BACK as work, not accepted — up to twice.
                if not verdict["verified"] and verify_fails < 2 and step < self.max_steps - 1:
                    verify_fails += 1
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": f"verifier rejected the finish: {verdict['reason']}"[:200]}}
                    self.log.append({"kind": "note", "summary": "verification REJECTED done",
                                     "observation": f"A strict verifier rejected your DONE: "
                                     f"{verdict['reason']}\nFix this and RUN it again to PROVE it "
                                     f"works before finishing."})
                    continue
                yield {"event": "operator_done", "data": {"summary": act["summary"],
                       "steps": step, "actions": len(self.log), "clean_runs": clean_runs,
                       "verified": bool(verdict["verified"]), "verification": verdict["reason"]}}
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
                # HARD anti-stall: a prompt nudge isn't always enough for a read-happy
                # model, so after 3 reads with no intervening change, refuse further
                # reads outright — force it to EDIT/WRITE. (Counts reads since the last
                # real action; notes/parse-fails don't reset it.)
                reads_since_act = 0
                for a in reversed(self.log):
                    if a["kind"] in ("write", "edit", "run"):
                        break
                    if a["kind"] == "read":
                        reads_since_act += 1
                if reads_since_act >= 3:
                    self.log.append({"kind": "note", "summary": "read blocked — must act",
                                     "observation": "READ is disabled: you've read 3+ times without "
                                     "changing anything. You already have what you need. Take an "
                                     "`EDIT:` or `WRITE:` action to fix the problem NOW, then `RUN:` "
                                     "it. You may not read again until you have made a change."})
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "read blocked after 3 reads — must EDIT/WRITE now"}}
                    continue
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
                    self.log.append({"kind": "write", "changed": True,
                                     "summary": f"wrote {act['path']} ({len(act['content'])} bytes)",
                                     "observation": f"wrote {act['path']}"})
                except Exception as exc:
                    self.log.append({"kind": "write", "summary": f"write {act['path']} failed",
                                     "observation": f"error: {exc}"[:300]})
                    yield {"event": "agent_note", "data": {"text": f"write failed: {exc}"[:160]}}
                continue

            # ── EDIT (surgical search/replace in an existing file) ──
            if tool == "edit":
                path, old, new = act["path"], act["old"], act["new"]
                try:
                    content = self.sb.read_file(path)
                except Exception as exc:
                    self.log.append({"kind": "edit", "summary": f"edit {path} — can't read",
                                     "observation": f"error: {exc}. WRITE the file first if it's new."})
                    yield {"event": "agent_note", "data": {"text": f"edit: can't read {path}"[:160]}}
                    continue
                n = content.count(old)
                if n == 0:
                    # Search/replace missed — a dead end if we just tell it to "read and
                    # retry" (that feeds the read-stall). Give it the EXACT current content
                    # inline and steer to rewrite the WHOLE file, which needs no matching.
                    self.log.append({"kind": "edit", "summary": f"edit {path} — text not found",
                                     "observation": "Your SEARCH text did not match the file EXACTLY, so "
                                     f"NOTHING changed. Do NOT guess the search text again — instead "
                                     f"`WRITE: {path}` the ENTIRE corrected file in one fenced block. "
                                     f"Here is its EXACT current content to correct:\n\n{content[:1600]}"})
                    yield {"event": "agent_note", "data": {"text":
                           f"edit didn't match {path} — rewriting the whole file instead"}}
                    continue
                if n > 1:
                    self.log.append({"kind": "edit", "summary": f"edit {path} — text not unique",
                                     "observation": f"The SEARCH text appears {n} times — add surrounding "
                                     "lines so it matches exactly ONE place."})
                    yield {"event": "agent_note", "data": {"text": f"edit: SEARCH not unique ({n}x) in {path}"}}
                    continue
                try:
                    fc = self.sb.write_file(path, content.replace(old, new, 1), reason="operator-edit")
                    yield {"event": "tool_call", "data": {"tool": "edit", "path": path}}
                    yield {"event": "file_changed", "data": {"path": path,
                           "diff": (fc.get("diff") or "")[:2500], "edit": True}}
                    self.log.append({"kind": "edit", "changed": True,
                                     "summary": f"edited {path} "
                                     f"(-{old.count(chr(10))+1}/+{new.count(chr(10))+1} lines)",
                                     "observation": f"applied search/replace to {path}"})
                except Exception as exc:
                    self.log.append({"kind": "edit", "summary": f"edit {path} failed",
                                     "observation": f"error: {exc}"[:300]})
                    yield {"event": "agent_note", "data": {"text": f"edit failed: {exc}"[:160]}}
                continue

            # ── RUN ──
            if tool == "run":
                cmd = act["command"]
                yield {"event": "command_started", "data": {"command": cmd}}
                r = self.sb.run(cmd, timeout=self.run_timeout, isolated=self.isolated)
                ran_something = True
                if r.get("exit_code") == 0 and not r.get("blocked"):
                    clean_runs += 1
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

            # ── FETCH (read the full text of a web page, read-only) ──
            if tool == "fetch":
                url = act["url"]
                if self.fetch is None:
                    self.log.append({"kind": "fetch", "summary": f"fetch {url} — unavailable",
                                     "observation": "web fetch isn't enabled on this host"})
                    yield {"event": "agent_note", "data": {"text": "fetch unavailable"}}
                    continue
                try:
                    r = self.fetch(url) or {}
                    text = (r.get("text") or "").strip()
                    obs = f"{r.get('url', url)} [{r.get('status', '?')}, {r.get('chars', len(text))} chars]\n{text[:3500]}"
                    yield {"event": "web_fetch", "data": {"url": r.get("url", url),
                           "status": r.get("status"), "chars": r.get("chars", len(text))}}
                    self.log.append({"kind": "fetch", "summary": f"fetched {url}",
                                     "observation": obs})
                except Exception as exc:
                    self.log.append({"kind": "fetch", "summary": f"fetch {url} failed",
                                     "observation": f"error: {exc}"[:300]})
                    yield {"event": "agent_note", "data": {"text": f"fetch failed: {exc}"[:160]}}
                continue

        # Budget hit: still render an HONEST verdict — run the strict verifier if
        # anything executed, otherwise it plainly did not finish.
        final = self._verify_goal(goal) if ran_something else {"verified": False,
                "reason": "step budget reached before anything ran"}
        yield {"event": "operator_done", "data": {"summary": "reached the step budget",
               "budget_hit": True, "steps": self.max_steps, "actions": len(self.log),
               "clean_runs": clean_runs, "verified": bool(final["verified"]),
               "verification": final.get("reason", "")}}
