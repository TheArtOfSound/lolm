# Copyright (c) 2026 Qira LLC. All rights reserved.
"""BYOK — bring your own keys, simply.

LOLM runs fully keyless (local model + keyless DuckDuckGo). Adding your own keys upgrades
it: a frontier brain, better web search, the shared 70B gateway, or your own local model.

Keys live in ONE file outside the repo (~/.lolm/keys.env, chmod 600) — never committed,
never sent anywhere but the API the key is for. `load_into_env()` loads them into the
process environment at startup WITHOUT clobbering anything already set in the real env (so
`export ANTHROPIC_API_KEY=…` still wins), which means every existing `os.environ.get(...)`
consumer in the codebase picks them up with zero rewiring. `set_keys()` updates the file and
the live environment together, so most keys take effect immediately.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

KEYFILE = Path(os.environ.get("LOLM_KEYFILE", "~/.lolm/keys.env")).expanduser()
_STRIPE_RE = re.compile(r"sk_(?:live|test)_[A-Za-z0-9]+")

# Only keys the code actually reads — so setting one always DOES something (no decoration).
KEY_SPECS: List[Dict[str, Any]] = [
    {"env": "ANTHROPIC_API_KEY", "label": "Anthropic (Claude)", "secret": True,
     "unlocks": "frontier-quality brain via the Claude bridge",
     "url": "https://console.anthropic.com/settings/keys", "group": "brain"},
    {"env": "WORKERS_AI_URL", "label": "LOLM 70B gateway URL", "secret": False,
     "unlocks": "the shared Cloudflare-hosted 70B brain", "url": "", "group": "brain"},
    {"env": "WORKERS_AI_SECRET", "label": "LOLM 70B gateway secret", "secret": True,
     "unlocks": "auth for the 70B gateway", "url": "", "group": "brain"},
    {"env": "LOLM_LOCAL_MODEL", "label": "Local model name", "secret": False,
     "unlocks": "a model on YOUR machine (e.g. qwen2.5:7b) — full sovereignty",
     "url": "https://ollama.com", "group": "local"},
    {"env": "LOLM_LOCAL_URL", "label": "Local model URL", "secret": False,
     "unlocks": "where your local model serves (e.g. http://127.0.0.1:11434)",
     "url": "", "group": "local"},
    {"env": "BRAVE_SEARCH_API_KEY", "label": "Brave Search", "secret": True,
     "unlocks": "higher-quality web search (vs keyless DuckDuckGo)",
     "url": "https://brave.com/search/api/", "group": "search"},
    {"env": "TAVILY_API_KEY", "label": "Tavily", "secret": True,
     "unlocks": "AI-tuned web search", "url": "https://tavily.com", "group": "search"},
    {"env": "SEARXNG_URL", "label": "SearXNG URL", "secret": False,
     "unlocks": "your self-hosted SearXNG instance", "url": "", "group": "search"},
    {"env": "STRIPE_SECRET_KEY", "label": "Stripe secret key", "secret": True,
     "unlocks": "the 'Support this project' donate button (server-side only, never exposed)",
     "url": "https://dashboard.stripe.com/apikeys", "group": "support"},
]
_VALID = {s["env"] for s in KEY_SPECS}


def load_into_env(path: Path = KEYFILE) -> int:
    """Load KEY=VALUE lines into os.environ; the real environment always wins over the file."""
    loaded = 0
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
                loaded += 1
    except FileNotFoundError:
        pass
    except Exception:
        pass
    loaded += 1 if _resolve_stripe_source() else 0
    return loaded


def _resolve_stripe_source() -> bool:
    """If STRIPE_SECRET_KEY_SOURCE points at an existing file (e.g. another project's .env),
    read the Stripe secret key OUT OF that file into the process env — without ever copying the
    value anywhere on disk. Only the PATH is stored; the key stays in its one original home and
    is loaded fresh each start. The real env always wins (an explicit export is never overridden)."""
    if os.environ.get("STRIPE_SECRET_KEY"):
        return False
    src = os.environ.get("STRIPE_SECRET_KEY_SOURCE", "").strip()
    if not src:
        return False
    try:
        m = _STRIPE_RE.search(Path(src).expanduser().read_text())
    except Exception:
        return False
    if m:
        os.environ["STRIPE_SECRET_KEY"] = m.group(0)
        return True
    return False


def set_stripe_source(path: str | Path, keyfile: Path = KEYFILE) -> Dict[str, Any]:
    """Point LOLM at an existing file that already holds your Stripe secret key, WITHOUT
    copying the key. Stores only the path in keys.env, then resolves it. Returns mode
    (live/test) derived from the key prefix — never the value."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": "file not found"}
    try:
        m = _STRIPE_RE.search(p.read_text())
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}
    if not m:
        return {"ok": False, "error": "no Stripe secret key (sk_live_/sk_test_) found in that file"}
    mode = "live" if m.group(0).startswith("sk_live_") else "test"
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    lines: Dict[str, str] = {}
    if keyfile.exists():
        for ln in keyfile.read_text().splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                lines[k.strip()] = v.strip()
    lines["STRIPE_SECRET_KEY_SOURCE"] = str(p)
    lines.pop("STRIPE_SECRET_KEY", None)            # always resolve from source, no stale copy
    keyfile.write_text("\n".join(f"{k}={v}" for k, v in lines.items()) + "\n")
    try:
        keyfile.chmod(0o600)
    except Exception:
        pass
    os.environ["STRIPE_SECRET_KEY_SOURCE"] = str(p)
    os.environ.pop("STRIPE_SECRET_KEY", None)
    return {"ok": True, "mode": mode, "loaded": _resolve_stripe_source(), "source": str(p)}


def set_keys(updates: Dict[str, str], path: Path = KEYFILE) -> int:
    """Merge updates into the keyfile AND the live environment. Empty value clears a key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    n = 0
    for k, v in (updates or {}).items():
        if k not in _VALID:
            continue
        v = (v or "").strip()
        if v:
            existing[k] = v
            os.environ[k] = v
        else:
            existing.pop(k, None)
            os.environ.pop(k, None)
        n += 1
    path.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + ("\n" if existing else ""))
    try:
        path.chmod(0o600)
    except Exception:
        pass
    return n


def _mask(v: str) -> str:
    if not v:
        return ""
    return ("•" * len(v)) if len(v) <= 8 else (v[:4] + "…" + v[-4:])


def status(reveal_preview: bool = True) -> Dict[str, Any]:
    """Masked, safe-to-display state of every known key (never the raw value)."""
    keys = []
    for s in KEY_SPECS:
        v = os.environ.get(s["env"], "")
        keys.append({k: s[k] for k in ("env", "label", "unlocks", "url", "secret", "group")}
                    | {"set": bool(v), "preview": (_mask(v) if (reveal_preview and v) else "")})
    return {"keys": keys, "keyfile": str(KEYFILE),
            "groups": ["brain", "local", "search", "support"]}
