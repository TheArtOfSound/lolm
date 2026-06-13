"""Client for the LOLM-NFET cloud brain (Cloudflare D1 via the lolm-edge worker).

The brain is a single shared memory + conversation store that every run anywhere
reads from and writes to, so the agent accumulates knowledge across all users
and sessions — the math/architecture made persistent and global. It runs on D1
(SQL), so it needs no Workers AI neurons and stays up even when generation quota
is exhausted.

Everything degrades gracefully: if the brain is unreachable, the agent falls
back to its local file memory and stateless single turns — never a hard failure.

Env:
    BRAIN_URL     base of the worker (e.g. https://lolm-edge.<acct>.workers.dev)
    BRAIN_SECRET  shared bearer secret (the worker's AI_SECRET)
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


class CloudBrain:
    def __init__(self, base_url: Optional[str] = None, secret: Optional[str] = None,
                 timeout: float = 6.0):
        self.base = (base_url or os.environ.get("BRAIN_URL", "")).rstrip("/")
        self.secret = secret or os.environ.get("BRAIN_SECRET", "")
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.base and self.secret)

    def _req(self, path: str, method: str = "GET",
             body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.secret}",
            "Content-Type": "application/json",
            "User-Agent": "lolm-nfet-origin/1.0",
        })
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    # -- conversation sessions (long-form memory) --------------------------
    def add_turn(self, session_id: str, role: str, content: str) -> bool:
        if not self.available() or not session_id:
            return False
        try:
            r = self._req("/brain/turn", "POST",
                          {"session_id": session_id, "role": role, "content": content})
            return bool(r.get("ok"))
        except Exception:
            return False

    def session_turns(self, session_id: str, limit: int = 40) -> List[Dict[str, Any]]:
        if not self.available() or not session_id:
            return []
        try:
            q = urllib.parse.urlencode({"id": session_id, "limit": limit})
            return self._req(f"/brain/session?{q}").get("turns", [])
        except Exception:
            return []

    # -- shared memory bank -----------------------------------------------
    def remember(self, text: str, kind: str = "learning", importance: int = 3,
                 source_session: Optional[str] = None) -> bool:
        if not self.available() or len((text or "").strip()) < 8:
            return False
        try:
            r = self._req("/brain/remember", "POST", {
                "text": text, "kind": kind, "importance": importance,
                "source_session": source_session,
            })
            return bool(r.get("ok"))
        except Exception:
            return False

    def recall(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        if not self.available() or not (query or "").strip():
            return []
        try:
            q = urllib.parse.urlencode({"q": query, "limit": limit})
            return self._req(f"/brain/recall?{q}").get("results", [])
        except Exception:
            return []

    def stats(self) -> Dict[str, Any]:
        try:
            return self._req("/brain/stats")
        except Exception:
            return {}
