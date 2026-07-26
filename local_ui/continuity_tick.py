# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Between-turn continuity maintenance — no model call, pure memory hygiene.

After each chat turn we:
  1. Ensure the last exchange is in rolling summaries
  2. Promote durable user lines into identity when capture signals fire
  3. Return a compact "continuity pack" the next turn can inject

This is the cheap half of "operator ticks between prompts" — always safe on
the public box, zero latency, no tokens burned.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_DURABLE = re.compile(
    r"\b(remember|my name|i prefer|i am |i'm |call me|my timezone|i work|i live|"
    r"my project|we use|our stack|don't |do not |always |never )\b",
    re.I,
)


def between_turn(
    memory: Any,
    *,
    user_text: str = "",
    assistant_text: str = "",
    session_id: str = "",
    promote: bool = False,
) -> Dict[str, Any]:
    """Run after a finished turn. Returns {summarized, promoted, continuity}."""
    out: Dict[str, Any] = {"summarized": False, "promoted": False, "continuity": ""}
    if memory is None:
        return out
    u = (user_text or "").strip()
    a = (assistant_text or "").strip()
    if not u and not a:
        return out
    span = session_id or "session"
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
    # Pack recent summaries + identity tail for the next request
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
