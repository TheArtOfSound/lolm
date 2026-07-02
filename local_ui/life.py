# Copyright (c) 2026 Qira LLC. All rights reserved.
"""LOLM's LIFE — the always-on pulse that keeps it thinking when nobody's watching.

Every tick (cron on the 24/7 box, ~20min): wake → look at goals + what it thought last
time + what changed (facts learned, evolution receipts) → think ONE genuinely new thought
with the best brain → optionally run ONE read-only web search to advance the focus →
journal it, remember what's durable, and record a PULSE. The site renders the pulse
trail, so walking in mid-thought is the normal experience, not a demo.

Honesty rules: a pulse is written ONLY for work that actually happened (a search that ran,
a note that was written). If no tick has fired, /api/demo/life says asleep — never fakes.
Safety: read-only by construction — the tick can think, search, and write to ITS OWN
memory/journal; it has no shell, no file mutation, no outbound actions.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request                 # module-level: with `from __future__ import
from fastapi.responses import JSONResponse  # annotations`, FastAPI must resolve these names

# standing curiosities used when no explicit goal is active — rotated so ticks don't rut
_STANDING = [
    "Review the workspace's recent activity and find one concrete way to answer better.",
    "Think about what today's learned facts connect to and what is worth learning next.",
    "Consider what a visitor is most likely to ask next and prepare the shape of a great answer.",
    "Reflect on the last few thoughts: what thread deserves to be pushed one step further?",
]


class LifeEngine:
    def __init__(self, runs_dir: Path, memory: Any,
                 chat_fn: Callable[[List[Dict[str, str]]], str],
                 search_fn: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
                 interval_s: int = 1200):
        self.runs = Path(runs_dir)
        self.runs.mkdir(parents=True, exist_ok=True)
        self.pulse_path = self.runs / "life_pulse.jsonl"
        self.memory = memory
        self.chat = chat_fn
        self.search = search_fn
        self.interval_s = interval_s

    # ── durable pulse trail ─────────────────────────────────────────────
    def _pulses(self, limit: int = 200) -> List[Dict[str, Any]]:
        if not self.pulse_path.exists():
            return []
        rows = []
        for ln in self.pulse_path.read_text().splitlines()[-limit:]:
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
        return rows

    @staticmethod
    def _sect(text: str, name: str) -> str:
        m = re.search(rf"^{name}:\s*(.+?)(?=^\s*(?:THOUGHT|SEARCH|REMEMBER|NEXT):|\Z)",
                      text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        return (m.group(1).strip() if m else "").strip()

    # ── one heartbeat ───────────────────────────────────────────────────
    def tick(self) -> Dict[str, Any]:
        t0 = time.time()
        pulses = self._pulses(limit=3)
        if pulses and t0 - pulses[-1].get("ts", 0) < self.interval_s * 0.5:
            return {"skipped": "pulsed recently", "last_ts": pulses[-1]["ts"]}

        goals = [g for g in self.memory.get_goals() if g.get("status", "active") == "active"]
        goals = sorted(goals, key=lambda g: int(g.get("priority", 3)), reverse=True)[:3]
        n_prev = len(self._pulses())
        focus = (f"Advance the goal: {goals[0].get('title','')} — {goals[0].get('why','')}".strip(" —")
                 if goals else _STANDING[n_prev % len(_STANDING)])
        prev_thoughts = "\n".join(f"- {p.get('thought','')[:220]}" for p in pulses) or "(none yet)"
        recent_learned = [n.get("text", "")[:180] for n in self.memory.recent_notes(limit=6)
                          if n.get("tag") in ("life", "self_tick")]

        prompt = (
            f"FOCUS:\n{focus}\n\n"
            f"YOUR LAST THOUGHTS (do NOT repeat or rephrase these — build on or depart from them):\n{prev_thoughts}\n\n"
            f"RECENTLY LEARNED:\n" + ("\n".join("- " + x for x in recent_learned) or "(nothing yet)") + "\n\n"
            f"JOURNAL TAIL:\n{self.memory.read_journal(max_chars=1200)}\n\n"
            "Return EXACTLY these four sections:\n"
            "THOUGHT: one short paragraph of genuinely NEW thinking on the focus — a hypothesis, "
            "a connection, a plan step; never a summary of the state above.\n"
            "SEARCH: one specific web query that would advance this (or NONE).\n"
            "REMEMBER: one durable insight worth keeping (or NONE).\n"
            "NEXT: the single concrete thing the next tick should do."
        )
        raw = self.chat([
            {"role": "system", "content":
                "You are LOLM's continuous mind — the thread of thought that runs while no one is "
                "watching. Think concretely and honestly; never claim actions you did not take."},
            {"role": "user", "content": prompt},
        ]) or ""
        thought = self._sect(raw, "THOUGHT") or raw.strip()[:400]
        query = self._sect(raw, "SEARCH")
        remember = self._sect(raw, "REMEMBER")
        nxt = self._sect(raw, "NEXT")

        # ONE read-only search, digested into something actually learned
        learned, sources = "", []
        if query and query.upper() != "NONE" and self.search is not None:
            try:
                hits = (self.search(query) or [])[:3]
                sources = [{"title": h.get("title", ""), "url": h.get("url", "")} for h in hits]
                if hits:
                    snip = "\n".join(f"- {h.get('title','')}: {h.get('snippet','')}" for h in hits)
                    learned = (self.chat([
                        {"role": "system", "content": "Distill ONLY what these snippets actually establish. Two sentences max; no speculation."},
                        {"role": "user", "content": f"QUERY: {query}\n\nSNIPPETS:\n{snip}"},
                    ]) or "").strip()[:500]
            except Exception:
                query, learned = f"{query} (search failed)", ""

        # write it into the workspace's real memory — this is how ticks compound
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(t0))
        pid = uuid.uuid4().hex[:8]
        self.memory.append_journal(
            f"## Life pulse {pid} @ {stamp}\n\nFOCUS: {focus}\n\n{thought}"
            + (f"\n\nSEARCHED: {query}\nLEARNED: {learned}" if learned else "")
            + (f"\n\nNEXT: {nxt}" if nxt else ""))
        if remember and remember.upper() != "NONE":
            self.memory.append_note(remember[:600], tag="life", importance=4)
        if learned:
            self.memory.append_note(f"Learned (autonomous, {stamp}): {learned}", tag="life", importance=4)

        pulse = {"id": pid, "ts": round(t0, 1), "focus": focus[:220], "thought": thought[:500],
                 "search": (query or "")[:160], "learned": learned[:500], "next": (nxt or "")[:220],
                 "sources": sources, "seconds": round(time.time() - t0, 1)}
        with self.pulse_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(pulse, ensure_ascii=False) + "\n")
        return pulse

    # ── what the site renders ───────────────────────────────────────────
    def status(self, since_ts: float = 0.0) -> Dict[str, Any]:
        pulses = self._pulses()
        now = time.time()
        last = pulses[-1] if pulses else None
        alive = bool(last and now - last["ts"] < self.interval_s * 2.5)
        day0 = now - (now % 86400)
        today = [p for p in pulses if p["ts"] >= day0]
        away = [p for p in pulses if since_ts and p["ts"] > since_ts][-24:]
        goals = [g for g in self.memory.get_goals() if g.get("status", "active") == "active"]
        return {
            "alive": alive,
            "last_pulse": last,
            "seconds_since": round(now - last["ts"]) if last else None,
            "next_eta_s": max(0, round(self.interval_s - (now - last["ts"]))) if last else None,
            "interval_s": self.interval_s,
            "pulses_today": len(today),
            "learned_today": sum(1 for p in today if p.get("learned")),
            "recent": pulses[-12:][::-1],
            "while_away": away[::-1],
            "goals": [{"title": g.get("title", ""), "why": g.get("why", "")} for g in goals[:5]],
            "note": ("thinking around the clock on the server" if alive else
                     "asleep — no pulse yet; the life tick hasn't run (nothing fabricated)"),
        }


def register_life_routes(app: Any, engine: LifeEngine, is_loopback: Callable[[Any], bool]) -> None:
    @app.get("/api/demo/life")
    def life_status(request: Request, since: float = 0.0):
        return engine.status(since_ts=since)

    @app.post("/api/demo/life/tick")
    def life_tick(request: Request):
        # the heartbeat is driven by the box's own cron — never by visitors
        if not is_loopback(request):
            return JSONResponse({"error": "the pulse is internal"}, status_code=403)
        try:
            return engine.tick()
        except Exception as exc:
            return JSONResponse({"error": str(exc)[:200]}, status_code=500)
