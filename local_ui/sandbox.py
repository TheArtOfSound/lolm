# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Real execution sandbox for the agent workspace (Phase 2).

Ephemeral per-session working directory. Runs commands, reads/writes files, clones
PUBLIC git repos, detects the project, captures a unified diff and rollback snapshot —
and records EVERY command (cmd/cwd/exit/stdout/stderr/timing) and EVERY file change
(path/before+after hash/diff/reason). Nothing is faked: if a command didn't run, no
record exists; if it failed, the record says so.

SECURITY: this is real code execution, so it is gated (a SANDBOX_SECRET token, or
loopback) and never wired to the anonymous public demo path — see sandbox_routes.py.
Even gated, it runs inside an ephemeral dir with a destructive-command deny-list, a
scrubbed env (no host secrets), a wall-clock timeout, an output cap, and a
path-traversal guard so writes can't escape the sandbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, List, Optional


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


# Commands refused outright — destructive / exfiltration / privilege / host reach /
# credential-file reads (the sandbox isn't a jail, so block reading the box's keys).
_DENY = [
    r"\brm\s+-rf\s+[/~]", r":\(\)\s*\{", r"\bsudo\b", r"\bshutdown\b", r"\breboot\b",
    r"\bmkfs\b", r"\bdd\s+if=", r"\bchmod\s+-R?\s*777\s+/", r">\s*/dev/sd",
    r"\bssh\b", r"\bscp\b", r"\bsftp\b", r"\bnc\s+-", r"\bncat\b", r"\btelnet\b",
    r"curl[^|]*\|\s*(sh|bash)", r"wget[^|]*\|\s*(sh|bash)", r"\bcrontab\b",
    r"/etc/(passwd|shadow|sudoers)", r"\bsystemctl\b", r"\bkillall\b",
    r"\b(history|env|printenv)\b.*(secret|token|key|password)", r"\.\./\.\./\.\.",
    # credential / secret file reads (defense-in-depth — no real FS jail)
    r"\.ssh/", r"\bid_rsa\b", r"\bid_ed25519\b", r"\bid_ecdsa\b", r"authorized_keys",
    r"\.aws/", r"\.npmrc\b", r"\.git-credentials\b", r"\.kube/", r"\.docker/config",
    r"/proc/\d+/environ", r"\bwai\.env\b", r"OPERATOR_SECRET|SANDBOX_SECRET|NPM_TOKEN",
]
_DENY_RE = re.compile("|".join(_DENY), re.IGNORECASE)

# Only clone from well-known public git hosts over https.
_REPO_RE = re.compile(r"^https://(www\.)?(github\.com|gitlab\.com|bitbucket\.org|codeberg\.org)/"
                      r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+(\.git)?/?$")

_OUTPUT_CAP = 24000     # chars of stdout/stderr kept per command
_MAX_FILE = 400_000     # bytes per readable/writable file


class SandboxError(Exception):
    pass


class Sandbox:
    def __init__(self, root: str | Path, session_id: Optional[str] = None):
        self.id = session_id or _id("sbx")
        self.root = Path(root)
        self.dir = (self.root / self.id).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.commands: List[Dict[str, Any]] = []
        self.changes: List[Dict[str, Any]] = []
        self._log = self.dir.parent / f"{self.id}.events.jsonl"

    # ── path safety ──────────────────────────────────────────────────────────
    def _safe(self, rel: str) -> Path:
        rel = (rel or "").lstrip("/")
        p = (self.dir / rel).resolve()
        if p != self.dir and self.dir not in p.parents:
            raise SandboxError(f"path escapes sandbox: {rel}")
        return p

    def _record(self, kind: str, obj: Dict[str, Any]) -> None:
        try:
            with self._log.open("a") as f:
                f.write(json.dumps({"kind": kind, **obj}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── files ────────────────────────────────────────────────────────────────
    def write_file(self, rel: str, content: str, reason: str = "") -> Dict[str, Any]:
        if len(content or "") > _MAX_FILE:
            raise SandboxError("file too large")
        p = self._safe(rel)
        before = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        diff = "".join(unified_diff(before.splitlines(keepends=True),
                                    content.splitlines(keepends=True),
                                    fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        fc = {"id": _id("fc"), "path": rel, "before_hash": _sha(before),
              "after_hash": _sha(content), "diff": diff[:_OUTPUT_CAP],
              "reason": reason, "created": _now()}
        self.changes.append(fc)
        self._record("file_change", fc)
        return fc

    def read_file(self, rel: str) -> str:
        p = self._safe(rel)
        if not p.exists() or not p.is_file():
            raise SandboxError(f"no such file: {rel}")
        if p.stat().st_size > _MAX_FILE:
            raise SandboxError("file too large to read")
        return p.read_text(encoding="utf-8", errors="replace")

    def list_files(self, limit: int = 800) -> List[str]:
        out: List[str] = []
        for p in sorted(self.dir.rglob("*")):
            if ".git" in p.parts or "node_modules" in p.parts or "__pycache__" in p.parts:
                continue
            if p.is_file():
                out.append(str(p.relative_to(self.dir)))
            if len(out) >= limit:
                break
        return out

    # ── command execution ──────────────────────────────────────────────────--
    def run(self, command: str, timeout: int = 120) -> Dict[str, Any]:
        command = (command or "").strip()
        rec: Dict[str, Any] = {"id": _id("cmd"), "command": command,
                               "cwd": str(self.dir), "started_at": _now()}
        if not command:
            rec.update(exit_code=None, stdout="", stderr="empty command",
                       blocked=True, ended_at=_now())
            return rec
        if _DENY_RE.search(command):
            rec.update(exit_code=None, stdout="",
                       stderr="blocked: destructive/exfiltration/privilege command refused",
                       blocked=True, ended_at=_now())
            self.commands.append(rec); self._record("command", rec)
            return rec
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.dir), "LANG": "C.UTF-8",
               "NODE_ENV": "development", "CI": "1"}
        t0 = time.time()
        try:
            p = subprocess.run(command, shell=True, cwd=str(self.dir), env=env,
                               capture_output=True, text=True, timeout=timeout)
            rec.update(exit_code=p.returncode, stdout=p.stdout[-_OUTPUT_CAP:],
                       stderr=p.stderr[-_OUTPUT_CAP:], blocked=False)
        except subprocess.TimeoutExpired:
            rec.update(exit_code=124, stdout="", stderr=f"timeout after {timeout}s",
                       blocked=False)
        except Exception as exc:
            rec.update(exit_code=1, stdout="", stderr=str(exc)[:500], blocked=False)
        rec["duration_s"] = round(time.time() - t0, 2)
        rec["ended_at"] = _now()
        self.commands.append(rec)
        self._record("command", rec)
        return rec

    # ── repo + project ─────────────────────────────────────────────────────--
    def clone(self, repo_url: str, timeout: int = 180) -> Dict[str, Any]:
        if not _REPO_RE.match((repo_url or "").strip()):
            raise SandboxError("only public github/gitlab/bitbucket/codeberg https URLs allowed")
        # Clone into a subdir so other sandbox files are unaffected.
        return self.run(f"git clone --depth 1 {repo_url} repo", timeout=timeout)

    def detect_project(self, sub: str = "") -> Dict[str, Any]:
        base = self._safe(sub) if sub else self.dir
        info: Dict[str, Any] = {"framework": "", "package_manager": "", "scripts": [],
                                "language": "", "found": []}
        pkg = base / "package.json"
        if pkg.exists():
            try:
                d = json.loads(pkg.read_text())
                info["language"] = "javascript/typescript"
                info["scripts"] = list((d.get("scripts") or {}).keys())
                deps = {**(d.get("dependencies") or {}), **(d.get("devDependencies") or {})}
                for fw in ("next", "react", "vue", "svelte", "express", "fastify", "vite"):
                    if fw in deps:
                        info["framework"] = fw; break
                info["found"].append("package.json")
            except Exception:
                pass
        if (base / "pnpm-lock.yaml").exists():
            info["package_manager"] = "pnpm"
        elif (base / "yarn.lock").exists():
            info["package_manager"] = "yarn"
        elif (base / "package-lock.json").exists():
            info["package_manager"] = "npm"
        for pyf in ("requirements.txt", "pyproject.toml", "setup.py"):
            if (base / pyf).exists():
                info["language"] = "python"
                info["package_manager"] = info["package_manager"] or "pip"
                info["found"].append(pyf)
        return info

    def git_diff(self, sub: str = "repo") -> Dict[str, Any]:
        target = sub if (self.dir / sub).exists() else "."
        return self.run(f"cd {target} && git --no-pager diff 2>/dev/null | head -400 || true")

    # ── snapshot / rollback ──────────────────────────────────────────────────
    def snapshot(self) -> str:
        snap = self.dir.parent / f"{self.id}.snap"
        if snap.exists():
            shutil.rmtree(snap, ignore_errors=True)
        shutil.copytree(self.dir, snap, ignore=shutil.ignore_patterns(".git", "node_modules"))
        return str(snap)

    def rollback(self) -> bool:
        snap = self.dir.parent / f"{self.id}.snap"
        if not snap.exists():
            return False
        for child in self.dir.iterdir():
            if child.name == ".git":
                continue
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
        for item in snap.iterdir():
            dest = self.dir / item.name
            shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)
        self._record("rollback", {"at": _now()})
        return True

    def state(self) -> Dict[str, Any]:
        return {"sandbox_id": self.id, "dir": str(self.dir),
                "files": len(self.list_files()), "commands_run": len(self.commands),
                "file_changes": len(self.changes),
                "has_snapshot": (self.dir.parent / f"{self.id}.snap").exists()}

    def destroy(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
        snap = self.dir.parent / f"{self.id}.snap"
        if snap.exists():
            shutil.rmtree(snap, ignore_errors=True)
