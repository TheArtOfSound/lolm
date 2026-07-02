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
from pydantic import BaseModel

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
        # facts minted from what it learns — the weight-training daemon consumes these,
        # so a thought at 3am can literally be trained weights by morning
        self.fact_queue = self.runs / "evolve_knowledge" / "queue.jsonl"
        self.fact_queue.parent.mkdir(parents=True, exist_ok=True)
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

    _SECT_KEYS = "THOUGHT|SEARCH|REMEMBER|NEXT|QUESTION|ANSWER|TARGET|SUMMARY"

    @classmethod
    def _sect(cls, text: str, name: str) -> str:
        m = re.search(rf"^{name}:\s*(.+?)(?=^\s*(?:{cls._SECT_KEYS}):|\Z)",
                      text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        return (m.group(1).strip() if m else "").strip()

    # ── thought → fact → (the daemon's) weights ────────────────────────
    def _queued_facts(self) -> List[Dict[str, Any]]:
        if not self.fact_queue.exists():
            return []
        rows = []
        for ln in self.fact_queue.read_text().splitlines():
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
        return rows

    def _mint_fact(self, learned: str, context: str) -> Optional[Dict[str, Any]]:
        """Turn a learned digest into ONE trainable Q/A fact — or honestly decline.
        Only durable, source-established facts become weights; opinions and
        maybe-knowledge stay as notes."""
        raw = self.chat([
            {"role": "system", "content":
                "You turn a learned digest into ONE flashcard-style fact for weight training, "
                "ONLY if it is durable and clearly established by the digest. Reply EXACTLY:\n"
                "QUESTION: <a natural question a user could ask>\nANSWER: <one-sentence answer>\n"
                "TARGET: <one lowercase keyword that must appear in a correct answer>\n"
                "or the single word SKIP if the digest is opinion, transient, or too vague."},
            {"role": "user", "content": f"CONTEXT: {context[:200]}\n\nDIGEST:\n{learned}"},
        ]) or ""
        if "skip" in raw.strip().lower()[:12]:
            return None
        q = self._sect(raw, "QUESTION")
        a = self._sect(raw, "ANSWER")
        tgt = self._sect(raw, "TARGET").split()[0].lower().strip(".,") if self._sect(raw, "TARGET") else ""
        if not (q and a and tgt and tgt in a.lower()):
            return None                       # malformed or target not actually in the answer
        if any(f.get("q") == q for f in self._queued_facts()):
            return None                       # already queued
        return {"q": q, "a": a, "target": tgt, "source": "life", "ts": round(time.time(), 1)}

    def _queue_fact(self, fact: Dict[str, Any]) -> None:
        with self.fact_queue.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(fact, ensure_ascii=False) + "\n")

    # ── the human answers a question LOLM asked — its reply becomes memory ──
    def _answered_ids(self) -> set:
        p = self.runs / "life_answered.json"
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            return set()

    def answer(self, pulse_id: str, reply: str) -> Dict[str, Any]:
        reply = (reply or "").strip()[:1000]
        q = ""
        for p in self._pulses():
            if p.get("id") == pulse_id:
                q = p.get("question", "")
                break
        if reply:
            self.memory.append_note(
                f"Owner answered LOLM's question '{q[:160]}' → {reply}", tag="owner_answer", importance=6)
            self.memory.append_journal(f"## Owner answered {pulse_id}\n\nQ: {q}\n\nA: {reply}")
        ap = self.runs / "life_answered.json"
        done = self._answered_ids(); done.add(pulse_id)
        ap.write_text(json.dumps(sorted(done)[-2000:]))
        return {"ok": True, "recorded": bool(reply), "question": q}

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
            "Return EXACTLY these five sections:\n"
            "THOUGHT: one short paragraph of genuinely NEW thinking on the focus — a hypothesis, "
            "a connection, a plan step; never a summary of the state above.\n"
            "SEARCH: one specific web query that would advance this (or NONE).\n"
            "REMEMBER: one durable insight worth keeping (or NONE).\n"
            "QUESTION: one genuine, specific question for your human that would actually unblock or "
            "sharpen this focus — something only they can answer (a preference, a decision, missing "
            "context). Make it feel like you've been thinking and want their take. (or NONE)\n"
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
        question = self._sect(raw, "QUESTION")
        if question.upper().strip(" .") == "NONE" or len(question) < 8:
            question = ""
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

        # thought → fact: durable learnings are minted into the weight-training queue
        fact = self._mint_fact(learned, focus) if learned else None
        if fact:
            self._queue_fact(fact)

        # write it into the workspace's real memory — this is how ticks compound
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(t0))
        pid = uuid.uuid4().hex[:8]
        self.memory.append_journal(
            f"## Life pulse {pid} @ {stamp}\n\nFOCUS: {focus}\n\n{thought}"
            + (f"\n\nSEARCHED: {query}\nLEARNED: {learned}" if learned else "")
            + (f"\n\nQUEUED FOR WEIGHT TRAINING: {fact['q']}" if fact else "")
            + (f"\n\nNEXT: {nxt}" if nxt else ""))
        if remember and remember.upper() != "NONE":
            self.memory.append_note(remember[:600], tag="life", importance=4)
        if learned:
            self.memory.append_note(f"Learned (autonomous, {stamp}): {learned}", tag="life", importance=4)

        pulse = {"id": pid, "ts": round(t0, 1), "focus": focus[:220], "thought": thought[:500],
                 "search": (query or "")[:160], "learned": learned[:500], "next": (nxt or "")[:220],
                 "question": question[:300], "fact_queued": (fact or {}).get("q", ""),
                 "sources": sources, "seconds": round(time.time() - t0, 1)}
        with self.pulse_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(pulse, ensure_ascii=False) + "\n")
        return pulse

    # ── the nightly deep reflection: consolidate the day, promote the best facts ──
    def deep_tick(self) -> Dict[str, Any]:
        t0 = time.time()
        day = [p for p in self._pulses() if t0 - p.get("ts", 0) < 86400]
        if not day:
            return {"skipped": "no pulses in the last day to reflect on"}
        trail = "\n".join(f"- {p.get('thought','')[:200]}" + (f" [learned: {p['learned'][:120]}]" if p.get("learned") else "")
                          for p in day[-24:])
        raw = self.chat([
            {"role": "system", "content":
                "You are LOLM's nightly reflection. Consolidate the day's autonomous thoughts "
                "honestly — no invented achievements. Reply EXACTLY:\nSUMMARY: <3-4 sentences on "
                "the day's thread of thought and what advanced>\nFACT1|FACT2|FACT3 (each optional): "
                "Q: <question> || A: <one-sentence answer> || T: <lowercase keyword in the answer>\n"
                "Only include FACTs that are durable and clearly established."},
            {"role": "user", "content": f"THE DAY'S PULSES:\n{trail}"},
        ]) or ""
        summary = self._sect(raw, "SUMMARY") or raw.strip()[:500]
        minted = []
        for m in re.finditer(r"Q:\s*(.+?)\s*\|\|\s*A:\s*(.+?)\s*\|\|\s*T:\s*([a-z0-9-]+)", raw, re.IGNORECASE):
            q, a, tgt = m.group(1).strip(), m.group(2).strip(), m.group(3).lower().strip()
            if q and a and tgt in a.lower() and not any(f.get("q") == q for f in self._queued_facts()):
                fact = {"q": q, "a": a, "target": tgt, "source": "life_deep", "ts": round(t0, 1)}
                self._queue_fact(fact)
                minted.append(q)
        stamp = time.strftime("%Y-%m-%d", time.localtime(t0))
        self.memory.append_journal(f"## Daily reflection {stamp}\n\n{summary}"
                                   + (("\n\nPROMOTED TO TRAINING: " + "; ".join(minted)) if minted else ""))
        self.memory.add_summary(summary[:1200], span="life_day")
        pulse = {"id": uuid.uuid4().hex[:8], "ts": round(t0, 1), "focus": "Daily reflection",
                 "thought": summary[:500], "search": "", "learned": "",
                 "fact_queued": "; ".join(minted)[:220], "sources": [],
                 "deep": True, "seconds": round(time.time() - t0, 1)}
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
        facts = self._queued_facts()
        answered = self._answered_ids()
        open_q = None
        for p in reversed(pulses):                    # newest unanswered question it asked
            if p.get("question") and p["id"] not in answered:
                open_q = {"id": p["id"], "question": p["question"], "focus": p.get("focus", ""),
                          "thought": p.get("thought", ""), "ts": p["ts"]}
                break
        return {
            "alive": alive,
            "open_question": open_q,
            "last_pulse": last,
            "seconds_since": round(now - last["ts"]) if last else None,
            "next_eta_s": max(0, round(self.interval_s - (now - last["ts"]))) if last else None,
            "interval_s": self.interval_s,
            "pulses_today": len(today),
            "learned_today": sum(1 for p in today if p.get("learned")),
            "facts_queued": len(facts),
            "facts_queued_today": sum(1 for f in facts if f.get("ts", 0) >= day0),
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
    def life_tick(request: Request, deep: bool = False):
        # the heartbeat is driven by the box's own cron — never by visitors
        if not is_loopback(request):
            return JSONResponse({"error": "the pulse is internal"}, status_code=403)
        try:
            return engine.deep_tick() if deep else engine.tick()
        except Exception as exc:
            return JSONResponse({"error": str(exc)[:200]}, status_code=500)

    @app.get("/api/demo/life/facts")
    def life_facts():
        """Facts LOLM minted from its own thinking — the weight-training daemon (on the
        owner's machine) pulls these and trains them in, gated. Read-only."""
        return {"facts": engine._queued_facts()[-200:]}

    class _Answer(BaseModel):
        pulse_id: str
        reply: str = ""

    @app.post("/api/demo/life/answer")
    def life_answer(body: _Answer):
        """The human answers a question LOLM asked while thinking. Its reply becomes a
        durable memory — this is the two-way loop: it wonders, you tell it, it remembers."""
        try:
            return engine.answer(body.pulse_id, body.reply)
        except Exception as exc:
            return JSONResponse({"error": str(exc)[:200]}, status_code=500)
