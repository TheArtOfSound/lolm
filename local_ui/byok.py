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
from pathlib import Path
from typing import Any, Dict, List

KEYFILE = Path(os.environ.get("LOLM_KEYFILE", "~/.lolm/keys.env")).expanduser()

# Only keys the code actually reads — so setting one always DOES something (no decoration).
KEY_SPECS: List[Dict[str, Any]] = [
    {"env": "ANTHROPIC_API_KEY", "label": "Anthropic (Claude)", "secret": True,
     "unlocks": "frontier-quality brain — chat, verify, code, streaming builds, and it joins the ensemble race",
     "url": "https://console.anthropic.com/settings/keys", "group": "brain"},
    {"env": "GROQ_API_KEY", "label": "Groq (direct)", "secret": True,
     "unlocks": "your own fast frontier (Llama-70B / gpt-oss-120b on Groq) — chat, streaming, ensemble; no gateway needed",
     "url": "https://console.groq.com/keys", "group": "brain"},
    {"env": "CEREBRAS_API_KEY", "label": "Cerebras (direct)", "secret": True,
     "unlocks": "your own ultra-fast frontier (GLM-4.7 on Cerebras) — chat, streaming, ensemble diversity",
     "url": "https://cloud.cerebras.ai", "group": "brain"},
    {"env": "OPENAI_API_KEY", "label": "OpenAI (direct)", "secret": True,
     "unlocks": "OpenAI as a direct brain + ensemble candidate",
     "url": "https://platform.openai.com/api-keys", "group": "brain"},
    {"env": "TOGETHER_API_KEY", "label": "Together (direct)", "secret": True,
     "unlocks": "open-weights frontier via Together — brain + ensemble candidate",
     "url": "https://api.together.ai", "group": "brain"},
    {"env": "OPENROUTER_API_KEY", "label": "OpenRouter (direct)", "secret": True,
     "unlocks": "one key, many models — brain + ensemble candidate",
     "url": "https://openrouter.ai/keys", "group": "brain"},
    {"env": "WORKERS_AI_URL", "label": "LOLM 70B gateway URL", "secret": False,
     "unlocks": "a 70B gateway (the shared LOLM one, or your own deployed edge worker)",
     "url": "", "group": "brain"},
    {"env": "WORKERS_AI_SECRET", "label": "LOLM 70B gateway secret", "secret": True,
     "unlocks": "auth for the 70B gateway", "url": "", "group": "brain"},
    {"env": "LOLM_BRAIN", "label": "Pin the brain", "secret": False,
     "unlocks": "force the voice: claude / local / 70b (default: best available)",
     "url": "", "group": "brain"},
    {"env": "LOLM_LOCAL_MODEL", "label": "Local model name", "secret": False,
     "unlocks": "a model on YOUR machine (e.g. qwen2.5:7b) — full sovereignty",
     "url": "https://ollama.com", "group": "local"},
    {"env": "LOLM_LOCAL_URL", "label": "Local model URL", "secret": False,
     "unlocks": "where your local model serves (e.g. http://127.0.0.1:11434)",
     "url": "", "group": "local"},
    {"env": "LOLM_LOCAL_API", "label": "Local API shape", "secret": False,
     "unlocks": "ollama or openai — openai unlocks LM Studio / vLLM / llama.cpp / the evolved-weights server on :11435",
     "url": "", "group": "local"},
    {"env": "LOLM_LOCAL_API_KEY", "label": "Local endpoint key", "secret": True,
     "unlocks": "auth for a keyed OpenAI-compatible endpoint (sent as Bearer)",
     "url": "", "group": "local"},
    {"env": "BRAVE_SEARCH_API_KEY", "label": "Brave Search", "secret": True,
     "unlocks": "higher-quality web search (vs keyless DuckDuckGo)",
     "url": "https://brave.com/search/api/", "group": "search"},
    {"env": "TAVILY_API_KEY", "label": "Tavily", "secret": True,
     "unlocks": "AI-tuned web search", "url": "https://tavily.com", "group": "search"},
    {"env": "SEARXNG_URL", "label": "SearXNG URL", "secret": False,
     "unlocks": "your self-hosted SearXNG instance", "url": "", "group": "search"},
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
    return loaded


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
