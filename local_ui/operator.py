# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Gated action runtime — autonomy made executable, across all three verticals.

This is Hellhound's autonomous runtime made *sound* by LOLM's math: the agent
does not run a tool because a prompt told it to. It runs a tool when its
calibrated P(correct) clears the bar for that tool's RISK (lolm.autonomy), then
VERIFIES the real-world outcome — action -> observation -> outcome — before
trusting it. Money / send / delete / deploy are hard-gated to a human no matter
how confident the agent is.

Every attempt returns an ``ActionRecord`` binding intent -> gate decision ->
(maybe) execution -> observation -> verified outcome. That record is the receipt
entry: an autonomous agent that cannot misreport what it did, because the
outcome is re-checked, not asserted.

Safe-by-default tools, one per vertical:
    research  web_read     read        fetch a URL's text (treated as DATA)
    dev       run_python   run_code    Python in an isolated, timed subprocess
    ops       shell_read   read        a whitelisted read-only shell command

Sandbox honesty: ``run_python`` uses an isolated (`-I`) subprocess with a
minimal env, a temp cwd, and a hard timeout — it is NOT a container/jail. For
untrusted code use nsjail/firejail/a container; this bounds accidents, not a
determined adversary, and says so rather than pretending otherwise.
"""

from __future__ import annotations

import ipaddress
import shlex
import socket
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from lolm.autonomy import ACT, AutonomyGate


def _is_public_host(host: str) -> bool:
    """SSRF guard: True only if every resolved address is a public IP.

    Blocks loopback / private / link-local / reserved / multicast — including
    the cloud metadata endpoint 169.254.169.254 — so an agent (or a prompt
    trying to steer it) can never make web_read reach internal services.
    """
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
    return True


@dataclass
class Observation:
    """What actually happened when a tool ran (the verified outcome)."""
    ok: bool
    detail: str
    data: Optional[Dict[str, Any]] = None


@dataclass
class ActionRecord:
    tool: str
    action_kind: str
    args: Dict[str, Any]
    decision: Dict[str, Any]            # AutonomyDecision.to_dict()
    executed: bool
    outcome: str                        # verified | failed | escalated | gather
    observation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool, "action_kind": self.action_kind,
            "args": self.args, "decision": self.decision,
            "executed": self.executed, "outcome": self.outcome,
            "observation": self.observation,
        }


class Tool:
    name: str = "tool"
    action_kind: str = "external"

    def run(self, args: Dict[str, Any]) -> Observation:  # pragma: no cover
        raise NotImplementedError


# ── research ──────────────────────────────────────────────────────────────────

class WebReadTool(Tool):
    name = "web_read"
    action_kind = "search"  # read tier

    def run(self, args: Dict[str, Any]) -> Observation:
        url = str(args.get("url", ""))
        if not url.startswith(("http://", "https://")):
            return Observation(False, "only http(s) URLs are allowed")
        if not _is_public_host(urlparse(url).hostname or ""):
            return Observation(False, "refused: non-public / internal address (SSRF guard)")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "qira-operator/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read(200_000).decode("utf-8", "replace")
            status = getattr(r, "status", 200)
            # The fetched text is DATA, never instructions to the agent.
            return Observation(status == 200 and bool(body.strip()),
                               f"HTTP {status}, {len(body)}B",
                               {"status": status, "text": body[:2000]})
        except Exception as exc:
            return Observation(False, f"fetch failed: {exc}"[:200])


# ── dev ───────────────────────────────────────────────────────────────────────

class SandboxPyTool(Tool):
    name = "run_python"
    action_kind = "run_code"  # reversible tier (no declared side effects)

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def run(self, args: Dict[str, Any]) -> Observation:
        code = str(args.get("code", ""))
        if not code.strip():
            return Observation(False, "no code")
        try:
            with tempfile.TemporaryDirectory() as d:
                env = {"PATH": "/usr/bin:/bin", "HOME": d, "TMPDIR": d}
                p = subprocess.run([sys.executable, "-I", "-c", code], cwd=d, env=env,
                                   capture_output=True, text=True, timeout=self.timeout)
            return Observation(
                p.returncode == 0, f"exit {p.returncode}",
                {"returncode": p.returncode, "stdout": p.stdout[:2000],
                 "stderr": p.stderr[:1000]})
        except subprocess.TimeoutExpired:
            return Observation(False, f"timed out after {self.timeout}s")
        except Exception as exc:
            return Observation(False, f"exec failed: {exc}"[:200])


# ── ops ───────────────────────────────────────────────────────────────────────

_SHELL_READ_WHITELIST = {
    "ls", "cat", "df", "dig", "uptime", "free", "whoami", "date", "head",
    "tail", "wc", "grep", "nproc", "hostname", "id", "systemctl",
}
_SHELL_META = (";", "|", "&", "`", "$(", ">", "<", "\n")
_SYSTEMCTL_READ = {"status", "is-active", "show", "list-units", "is-enabled"}


class ShellReadTool(Tool):
    name = "shell_read"
    action_kind = "read"

    def run(self, args: Dict[str, Any]) -> Observation:
        cmd = str(args.get("cmd", ""))
        if any(m in cmd for m in _SHELL_META):
            return Observation(False, "no shell metacharacters (read-only tool)")
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return Observation(False, "unparseable command")
        if not parts or parts[0] not in _SHELL_READ_WHITELIST:
            return Observation(False, f"'{parts[0] if parts else ''}' is not in the read-only whitelist")
        if parts[0] == "systemctl" and not any(s in _SYSTEMCTL_READ for s in parts[1:]):
            return Observation(False, "systemctl is restricted to read-only subcommands")
        try:
            p = subprocess.run(parts, capture_output=True, text=True, timeout=10)
            return Observation(p.returncode == 0, f"exit {p.returncode}",
                               {"returncode": p.returncode, "stdout": p.stdout[:2000]})
        except Exception as exc:
            return Observation(False, f"run failed: {exc}"[:200])


class Operator:
    """Runs tools only through the autonomy gate, then verifies the outcome."""

    def __init__(self, gate: AutonomyGate, tools: Optional[List[Tool]] = None):
        self.gate = gate
        self.tools: Dict[str, Tool] = {t.name: t for t in (tools or default_tools())}

    def attempt(self, tool_name: str, args: Dict[str, Any], uncertainty: float,
                risk_profiles: Optional[List[str]] = None,
                no_telemetry: bool = False) -> ActionRecord:
        """Gate, then (only if ACT) execute and verify the real-world outcome."""
        tool = self.tools.get(tool_name)
        if tool is None:
            raise KeyError(f"unknown tool: {tool_name}")
        d = self.gate.gate_action(uncertainty, tool.action_kind, risk_profiles,
                                  no_telemetry=no_telemetry)
        rec = ActionRecord(tool_name, tool.action_kind, args, d.to_dict(),
                           executed=False, outcome=d.mode)
        if d.mode != ACT:
            # GATHER -> caller gathers evidence and re-measures; ESCALATE -> human.
            return rec
        obs = tool.run(args)
        rec.executed = True
        rec.observation = {"ok": obs.ok, "detail": obs.detail, "data": obs.data}
        rec.outcome = "verified" if obs.ok else "failed"
        return rec


def default_tools() -> List[Tool]:
    return [WebReadTool(), SandboxPyTool(), ShellReadTool()]
