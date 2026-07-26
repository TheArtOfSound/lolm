# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Between-turn continuity maintenance.

After each chat turn we:
  1. Ensure the last exchange is in rolling summaries
  2. Promote durable user lines into identity when capture signals fire
  3. Return a compact "continuity pack" the next turn can inject
  4. Optionally run a *model-backed* micro-tick (local-only) to extract
     durable facts / open loops when a generate callback is provided

The default path is pure memory hygiene — always safe on the public box,
zero latency, no tokens burned. Model ticks are opt-in via `generate`.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional

_DURABLE = re.compile(
    r"\b(remember|my name|i prefer|i am |i'm |call me|my timezone|i work|i live|"
    r"my project|we use|our stack|don't |do not |always |never )\b",
    re.I,
)

# Heuristic fact lines the model-free path can still promote.
_FACT_LINE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:user\s+)?(?:name|prefers?|timezone|project|stack|works?|"
    r"lives?|always|never|don't|do not)[^\n]{4,120}$"
)
_NAME_INLINE = re.compile(
    r"\b(?:my name is|i am|i'm|call me|i am called)\s+([A-Z][a-zA-Z\-']{1,40})\b",
    re.I,
)
_PREFER_INLINE = re.compile(
    r"\b(?:i prefer|prefer(?:ence)?s?)\s+([^\n.!?]{3,80})",
    re.I,
)


def _heuristic_facts(user_text: str, assistant_text: str = "") -> List[str]:
    """Extract durable facts without a model call."""
    facts: List[str] = []
    u = (user_text or "").strip()
    if not u:
        return facts
    m = _NAME_INLINE.search(u)
    if m:
        facts.append(f"name is {m.group(1)}")
    m = _PREFER_INLINE.search(u)
    if m:
        facts.append(f"prefers {m.group(1).strip()}")
    if _DURABLE.search(u) and len(u) <= 160:
        # keep short durable statements as-is
        clean = re.sub(r"\s+", " ", u)
        if clean.lower() not in {f.lower() for f in facts}:
            facts.append(clean[:160])
    # model sometimes restates facts; harvest short assistant identity lines
    for line in (assistant_text or "").splitlines():
        if _FACT_LINE.match(line.strip()):
            facts.append(line.strip().lstrip("-* ").strip()[:120])
    # de-dupe
    seen = set()
    out: List[str] = []
    for f in facts:
        k = f.lower()
        if k not in seen and len(f) >= 6:
            seen.add(k)
            out.append(f)
    return out[:4]


def _apply_facts(memory: Any, facts: List[str]) -> int:
    n = 0
    if memory is None or not facts:
        return 0
    for f in facts:
        try:
            if hasattr(memory, "append_identity_line"):
                before = memory.read_identity() if hasattr(memory, "read_identity") else ""
                memory.append_identity_line(f"from chat: {f}")
                after = memory.read_identity() if hasattr(memory, "read_identity") else before
                if after != before:
                    n += 1
            if hasattr(memory, "append_note"):
                memory.append_note(f, tag="fact", importance=5)
        except Exception:
            pass
    return n


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def model_tick_allowed() -> bool:
    """Model-backed ticks: explicit LOLM_MODEL_TICK or operator-local boxes."""
    return _env_truthy("LOLM_MODEL_TICK") or _env_truthy("LOLM_OPERATOR_LOCAL")


def resolve_local_tick_generate(
    generate: Optional[Callable[[str], str]] = None,
) -> Optional[Callable[[str], str]]:
    """Return a generate(prompt)->text callable for local ticks, or None.

    Prefer an injected callback. Otherwise, when model ticks are allowed, try
    the evolved / local OpenAI-compatible endpoint (cheap, short completion).
    Never raises; never hits remote frontier APIs.
    """
    if generate is not None:
        return generate
    if not model_tick_allowed():
        return None
    try:
        from local_ui.local_brain import (
            evolved_url, probe_evolved, EVOLVED_DEFAULT_MODEL, EVOLVED_DEFAULT_API,
        )
        import json
        import urllib.request
    except Exception:
        return None

    url = (os.environ.get("LOLM_LOCAL_URL", "") or "").strip().rstrip("/")
    model = (os.environ.get("LOLM_LOCAL_MODEL", "") or "").strip()
    api = (os.environ.get("LOLM_LOCAL_API", "") or "").strip().lower()
    if not url or not model:
        eurl = evolved_url()
        if not probe_evolved(eurl):
            return None
        url, model, api = eurl, EVOLVED_DEFAULT_MODEL, EVOLVED_DEFAULT_API
    if not api:
        api = "openai" if "11435" in url or model == EVOLVED_DEFAULT_MODEL else "ollama"

    def _gen(prompt: str) -> str:
        msgs = [
            {"role": "system", "content": "You extract durable chat facts. Be terse."},
            {"role": "user", "content": prompt[:1200]},
        ]
        if api == "openai":
            endpoint = url + "/v1/chat/completions"
            payload = {
                "model": model, "messages": msgs, "stream": False,
                "max_tokens": 96, "temperature": 0.1,
            }
        else:
            endpoint = url + "/api/chat"
            payload = {
                "model": model, "messages": msgs, "stream": False,
                "options": {"temperature": 0.1, "num_predict": 96},
            }
        headers = {"Content-Type": "application/json", "User-Agent": "lolm-tick/1.0"}
        key = os.environ.get("LOLM_LOCAL_API_KEY", "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        if api == "openai":
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
        return (data.get("message") or {}).get("content", "") or ""

    return _gen


def model_backed_tick(
    memory: Any,
    *,
    user_text: str,
    assistant_text: str,
    session_id: str = "",
    generate: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Optional local-only micro-tick: extract durable facts + open loop.

    `generate` should be a cheap local completion (e.g. evolved :11435). When
    absent or disabled, falls back to heuristic fact extraction only.
    Returns {facts, open_loop, model_used, promoted}.
    """
    out: Dict[str, Any] = {
        "facts": [], "open_loop": "", "model_used": False, "promoted": 0,
    }
    u = (user_text or "").strip()
    a = (assistant_text or "").strip()
    if not u and not a:
        return out

    facts = _heuristic_facts(u, a)
    open_loop = ""
    used_model = False

    gen = resolve_local_tick_generate(generate)
    if gen is not None and (u or a):
        prompt = (
            "Extract continuity from this chat turn. Reply with EXACTLY two lines:\n"
            "FACTS: <comma-separated durable user facts, or none>\n"
            "OPEN: <one open question or next action, or none>\n\n"
            f"USER: {u[:400]}\nASSISTANT: {a[:500]}\n"
        )
        try:
            raw = (gen(prompt) or "").strip()
            used_model = True
            for line in raw.splitlines():
                low = line.strip()
                if low.upper().startswith("FACTS:"):
                    body = low.split(":", 1)[1].strip()
                    if body and body.lower() not in ("none", "n/a", "-"):
                        for part in re.split(r"[,;]|\s+\|\s+", body):
                            p = part.strip(" -")
                            if 6 <= len(p) <= 120:
                                facts.append(p)
                elif low.upper().startswith("OPEN:"):
                    body = low.split(":", 1)[1].strip()
                    if body and body.lower() not in ("none", "n/a", "-"):
                        open_loop = body[:200]
        except Exception:
            used_model = False

    # de-dupe facts
    seen = set()
    uniq: List[str] = []
    for f in facts:
        k = f.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    facts = uniq[:5]
    promoted = _apply_facts(memory, facts)
    if open_loop and memory is not None:
        try:
            if hasattr(memory, "add_summary"):
                memory.add_summary(f"open: {open_loop}", span=session_id or "session")
        except Exception:
            pass
    out["facts"] = facts
    out["open_loop"] = open_loop
    out["model_used"] = used_model
    out["promoted"] = promoted
    return out


def between_turn(
    memory: Any,
    *,
    user_text: str = "",
    assistant_text: str = "",
    session_id: str = "",
    promote: bool = False,
    generate: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Run after a finished turn. Returns {summarized, promoted, continuity, tick}."""
    out: Dict[str, Any] = {
        "summarized": False, "promoted": False, "continuity": "", "tick": {},
    }
    if memory is None:
        return out
    u = (user_text or "").strip()
    a = (assistant_text or "").strip()
    span = session_id or "session"
    # Optional write path: only when we have a new exchange
    if u or a:
        snippet = ""
        if u and a:
            snippet = (u[:120] + " → " + a.replace("\n", " ")[:180])
        elif u:
            snippet = u[:200]
        try:
            if snippet and hasattr(memory, "add_summary"):
                do_promote = bool(promote) or bool(_DURABLE.search(u))
                memory.add_summary(snippet, span=span, promote=do_promote)
                out["summarized"] = True
                out["promoted"] = do_promote
        except Exception:
            pass
        # Model-backed or heuristic micro-tick (facts + open loop)
        try:
            tick = model_backed_tick(
                memory,
                user_text=u,
                assistant_text=a,
                session_id=span,
                generate=generate,
            )
            out["tick"] = tick
            if tick.get("promoted"):
                out["promoted"] = True
        except Exception:
            out["tick"] = {}
    # Pack recent summaries + identity tail for the next request (read path always)
    bits: List[str] = []
    try:
        if hasattr(memory, "read_identity"):
            ident = (memory.read_identity() or "").strip()
            if ident:
                bits.append("IDENTITY:\n" + ident[-800:])
    except Exception:
        pass
    try:
        if hasattr(memory, "recent_summaries"):
            rows = memory.recent_summaries(4) or []
            if rows:
                lines = [str(r.get("summary") or "")[:200] for r in rows if r.get("summary")]
                if lines:
                    bits.append("RECENT THREAD:\n- " + "\n- ".join(lines))
    except Exception:
        pass
    out["continuity"] = "\n\n".join(bits)[:1600]
    return out
