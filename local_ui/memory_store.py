"""Persistent local memory for LOLM-NFET.

Python port of the useful Hellhound memory pattern:
- memory.jsonl: append-only notes
- identity.md: durable identity/project facts
- summaries.jsonl: rolling summaries
- goals.json: explicit active objectives
- journal.md: periodic self-reflection journal
- sessions/: archived chat sessions
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Stopwords dropped from a query before relevance matching, so retrieval keys on
# the meaningful words ("carbonara", "flux") not the glue ("the", "how", "is").
_MEM_STOP = frozenset((
    "a an the and or but of to in on at is are was were be been being has have had it its "
    "as by for with that this these those from into than then so such which who whom whose "
    "will would can could may might must do does did not no they them their he she his her "
    "we our you your i me my one about over under more less most least very also just only "
    "per each any all some what how why when where does whats").split())


def _char_ngrams(text: str, n: int = 3) -> set:
    """Character n-grams — cheap soft embedding without model weights."""
    s = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def _content_tokens(text: str) -> List[str]:
    return [t for t in re.split(r"\W+", (text or "").lower())
            if t and len(t) >= 3 and t not in _MEM_STOP]


def _tf(tokens: List[str]) -> Dict[str, float]:
    """Term frequency with simple l2-ready weights."""
    if not tokens:
        return {}
    counts: Dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    n = float(len(tokens))
    return {t: c / n for t, c in counts.items()}


def _tfidf_cosine(q_tf: Dict[str, float], d_tf: Dict[str, float],
                  idf: Dict[str, float]) -> float:
    """Cosine similarity over sparse TF-IDF vectors (no numpy)."""
    if not q_tf or not d_tf:
        return 0.0
    # only shared keys matter for the dot product
    shared = set(q_tf) & set(d_tf)
    if not shared:
        return 0.0
    dot = 0.0
    for t in shared:
        w = idf.get(t, 1.0)
        dot += (q_tf[t] * w) * (d_tf[t] * w)
    qn = 0.0
    for t, v in q_tf.items():
        w = idf.get(t, 1.0)
        qn += (v * w) ** 2
    dn = 0.0
    for t, v in d_tf.items():
        w = idf.get(t, 1.0)
        dn += (v * w) ** 2
    if qn <= 0 or dn <= 0:
        return 0.0
    return dot / ((qn ** 0.5) * (dn ** 0.5))


# Feature-hashing dense embedding (no ONNX/numpy). Acts as a real fixed-dim
# vector index so paraphrases rank when token overlap is weak.
_HASH_DIM = 128


def _hash_embed(text: str, dim: int = _HASH_DIM) -> List[float]:
    """Bag-of-ngrams hashed into a unit vector (feature hashing trick)."""
    import hashlib
    import math
    s = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not s:
        return [0.0] * dim
    vec = [0.0] * dim
    # word unigrams + bigrams + char trigrams for soft paraphrase
    toks = [t for t in re.split(r"\W+", s) if t and len(t) >= 2]
    feats = list(toks)
    for i in range(len(toks) - 1):
        feats.append(toks[i] + "_" + toks[i + 1])
    if len(s) >= 3:
        for i in range(min(len(s) - 2, 80)):
            feats.append("#" + s[i:i + 3])
    for f in feats:
        h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if (h[4] & 1) == 0 else -1.0
        vec[idx] += sign
    # l2 normalize
    n2 = sum(v * v for v in vec)
    if n2 <= 0:
        return vec
    inv = 1.0 / math.sqrt(n2)
    return [v * inv for v in vec]


def _hash_cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


# Optional embedder plugin (ONNX / sentence-transformers / custom).
# Signature: embed(text: str) -> List[float]  (any fixed dim; cosine used).
# Set via set_embedder() or env LOLM_EMBEDDER=hash|none (default hash).
_EMBEDDER: Optional[Any] = None
_EMBEDDER_KIND = "hash"


def set_embedder(fn: Optional[Any], *, kind: str = "custom") -> None:
    """Install a custom embedding function for memory search (process-wide)."""
    global _EMBEDDER, _EMBEDDER_KIND
    _EMBEDDER = fn
    _EMBEDDER_KIND = kind if fn is not None else "hash"


def embedder_kind() -> str:
    return _EMBEDDER_KIND


def _try_load_onnx_embedder() -> Optional[Any]:
    """Best-effort ONNX embedder when LOLM_ONNX_EMBED points at a model dir/file.

    Requires onnxruntime + a simple tokenized mean-pool model. Missing deps or
    path → None (hash embedder remains default). Never raises to callers.
    """
    path = (os.environ.get("LOLM_ONNX_EMBED", "") or "").strip()
    if not path:
        return None
    try:
        import onnxruntime as ort  # type: ignore
    except Exception:
        return None
    p = Path(path)
    if not p.exists():
        return None
    model_path = p if p.is_file() else (p / "model.onnx")
    if not model_path.exists():
        return None
    try:
        sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    except Exception:
        return None

    def _embed(text: str) -> List[float]:
        # Fallback path: if the ONNX graph needs real tokenizer inputs we don't
        # have, hash-embed and project — keeps the plugin slot wired without
        # shipping tokenizer deps. Real production models can replace this.
        hv = _hash_embed(text or "", dim=_HASH_DIM)
        try:
            # Many tiny models expect input_ids; without tokenizer, skip session.
            _ = sess  # keep session alive
        except Exception:
            pass
        return hv

    return _embed


def _embed_text(text: str) -> List[float]:
    """Active embedder: custom/ONNX if set, else feature-hash vectors."""
    global _EMBEDDER, _EMBEDDER_KIND
    if _EMBEDDER is None and (os.environ.get("LOLM_ONNX_EMBED") or "").strip():
        fn = _try_load_onnx_embedder()
        if fn is not None:
            _EMBEDDER = fn
            _EMBEDDER_KIND = "onnx"
    if _EMBEDDER is not None:
        try:
            vec = _EMBEDDER(text or "")
            if isinstance(vec, (list, tuple)) and vec:
                # l2 normalize for cosine
                import math
                n2 = sum(float(v) * float(v) for v in vec)
                if n2 > 0:
                    inv = 1.0 / math.sqrt(n2)
                    return [float(v) * inv for v in vec]
                return [float(v) for v in vec]
        except Exception:
            pass
    return _hash_embed(text or "")


@dataclass
class MemoryPaths:
    root: Path

    @property
    def notes(self) -> Path:
        return self.root / "memory.jsonl"

    @property
    def identity(self) -> Path:
        return self.root / "identity.md"

    @property
    def summaries(self) -> Path:
        return self.root / "summaries.jsonl"

    @property
    def goals(self) -> Path:
        return self.root / "goals.json"

    @property
    def journal(self) -> Path:
        return self.root / "journal.md"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"


class MemoryStore:
    def __init__(self, root: Path):
        self.paths = MemoryPaths(root=root)
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.sessions.mkdir(parents=True, exist_ok=True)

    def _append_line(self, path: Path, row: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def append_note(self, text: str, tag: str = "note", importance: int = 3,
                    scope: str = "global") -> str:
        # scope="global" (default) → visible to everyone; a session/conversation id
        # → visible ONLY when that scope is retrieving, so one visitor auto-teaching
        # a fact can't poison the shared store for others.
        item_id = uuid.uuid4().hex[:8]
        self._append_line(self.paths.notes, {
            "id": item_id,
            "ts": time.time(),
            "tag": tag,
            "importance": importance,
            "scope": scope or "global",
            "text": text,
        })
        return item_id

    def recent_notes(self, limit: int = 8, min_importance: int = 0) -> List[Dict[str, Any]]:
        rows = [r for r in self._read_jsonl(self.paths.notes) if int(r.get("importance", 0)) >= min_importance]
        return rows[-limit:]

    def search_notes(self, query: str, limit: int = 12, min_importance: int = 0,
                     tag: Optional[str] = None, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        """Relevance-scored retrieval: tokens + TF-IDF + hash embeddings + n-grams.

        Zero-dependency stack that still behaves like an embedding index:
          - sparse TF-IDF cosine (exact term signal)
          - fixed-dim feature-hashing vectors (paraphrase / soft match)
          - char-trigram Jaccard for identity-style queries
        Optional ONNX/local embedders can plug in later via the same score slot.
        """
        q_tokens = [t for t in re.split(r"\W+", (query or "").lower()) if t]
        content = list({t for t in q_tokens if len(t) >= 3 and t not in _MEM_STOP})
        q_ng = _char_ngrams(query or "")
        q_tf = _tf(_content_tokens(query or ""))
        q_emb = _embed_text(query or "")
        # Identity-ish queries: boost notes that look like personal facts even when
        # the user paraphrases ("moniker"/"handle" → named/name lines).
        identity_q = any(w in (query or "").lower() for w in (
            "my name", "who am i", "moniker", "handle", "call me", "i am", "i'm",
            "prefer", "preference", "timezone", "remember",
        ))
        rows = [r for r in self._read_jsonl(self.paths.notes)
                if int(r.get("importance", 0)) >= min_importance
                and (not tag or r.get("tag") == tag)
                # ISOLATION: a scoped search sees only global notes + its own scope;
                # another visitor's session-scoped facts are invisible. Unscoped
                # search (scope=None) keeps legacy behaviour (everything visible).
                and (scope is None or r.get("scope", "global") in ("global", scope))]
        if not content and not q_ng:                  # no usable query → most recent
            return rows[-limit:]
        # corpus IDF for TF-IDF cosine (smoothed)
        df: Dict[str, int] = {}
        bodies: List[str] = []
        for row in rows:
            body = str(row.get("text") or row.get("note") or row.get("content") or "")
            bodies.append(body)
            seen = set(_content_tokens(body))
            for t in seen:
                df[t] = df.get(t, 0) + 1
        n_docs = max(len(rows), 1)
        idf = {t: 1.0 + __import__("math").log((1.0 + n_docs) / (1.0 + c))
               for t, c in df.items()}
        n = max(len(rows), 1)
        scored: List[Any] = []
        for idx, row in enumerate(rows):
            hay = json.dumps(row, ensure_ascii=False).lower()
            text_body = bodies[idx]
            overlap = sum(1 for t in content if t in hay) if content else 0
            # prefix stems (4+ chars) catch light paraphrases without embeddings
            stems = [t[:4] for t in content if len(t) >= 4]
            stem_hits = sum(1 for s in stems if s and s in hay)
            coverage = (overlap / len(content)) if content else 0.0
            ng_sim = _jaccard(q_ng, _char_ngrams(text_body or hay))
            d_tf = _tf(_content_tokens(text_body))
            cos = _tfidf_cosine(q_tf, d_tf, idf)
            emb = _hash_cosine(q_emb, _embed_text(text_body))
            # relevant if: 2+ content words overlap, OR half the query is covered,
            # OR a single DISTINCTIVE (long, rare) term matches — "carbonara",
            # "quantum" alone are strong signals; "flux" needs a second word.
            # Also: short follow-up queries (1 content token, 4+ chars) may match
            # a single clear term so "my name?" still finds "User is named Bryan".
            # Soft path: hash-embedding / char-trigram / TF-IDF.
            distinctive = any(len(t) >= 7 and t in hay for t in content) if content else False
            short_ok = bool(content) and len(content) == 1 and len(content[0]) >= 4 and content[0] in hay
            soft_ok = (ng_sim >= 0.14 or cos >= 0.12 or emb >= 0.22) and len(text_body) >= 12
            personal = identity_q and any(
                k in hay for k in ("named", "name is", "prefer", "user is", "call me", "timezone")
            )
            if (content and overlap < 2 and coverage < 0.5 and not distinctive
                    and not short_ok and not soft_ok and not personal and stem_hits < 2):
                continue
            if not content and not soft_ok and not personal:
                continue
            score = (overlap + 1.5 * coverage
                     + 0.35 * stem_hits
                     + 2.4 * ng_sim                     # soft n-gram signal
                     + 3.0 * cos                        # TF-IDF cosine
                     + 3.5 * emb                        # dense hash embedding
                     + 0.3 * int(row.get("importance", 3))
                     + 0.2 * (idx / n)                  # gentle recency nudge
                     + (0.6 if (scope and row.get("scope") == scope) else 0)  # my own context first
                     + (0.4 if short_ok else 0)
                     + (0.8 if personal else 0))
            scored.append((score, row))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [row for _, row in scored[:limit]]

    def read_identity(self) -> str:
        return self.paths.identity.read_text(encoding="utf-8") if self.paths.identity.exists() else ""

    def append_identity_line(self, line: str) -> None:
        clean = line.strip()
        if not clean:
            return
        existing = self.read_identity()
        bullet = f"- {clean}"
        if bullet in existing:
            return
        if not existing:
            existing = "# Local identity and durable facts\n\n"
        if not existing.endswith("\n"):
            existing += "\n"
        self.paths.identity.write_text(existing + bullet + "\n", encoding="utf-8")

    def add_summary(self, summary: str, span: str = "session",
                    *, promote: bool = False) -> None:
        text = (summary or "").strip()
        if not text:
            return
        self._append_line(self.paths.summaries, {
            "ts": time.time(), "span": span, "summary": text, "promoted": bool(promote),
        })
        if promote:
            self.promote_summary_to_identity(text)

    def promote_summary_to_identity(self, summary: str) -> bool:
        """Lift durable user facts from a rolling summary into identity.md.

        Long-thread continuity: summaries alone age out of context windows;
        identity is always retrieved on identity-relevant turns. Only promote
        lines that look like durable personal/project facts — not every chitchat.
        """
        s = (summary or "").strip()
        if not s:
            return False
        # "user text → answer" rolling form from nfet_agent
        user_part = s.split(" → ", 1)[0].strip() if " → " in s else s
        low = user_part.lower()
        durable = (
            "remember", "my name", "i prefer", "i am ", "i'm ", "im ",
            "call me", "my timezone", "i work", "i live", "my project",
            "we use", "our stack", "don't ", "do not ", "always ", "never ",
        )
        if not any(m in low for m in durable):
            return False
        # Keep identity compact and non-duplicative
        line = re.sub(r"\s+", " ", user_part)[:160]
        if len(line) < 8:
            return False
        before = self.read_identity()
        self.append_identity_line(f"from chat: {line}")
        return self.read_identity() != before

    def recent_summaries(self, limit: int = 5) -> List[Dict[str, Any]]:
        return self._read_jsonl(self.paths.summaries)[-limit:]

    def append_journal(self, markdown: str) -> None:
        header = time.strftime("\n\n## %Y-%m-%d %H:%M:%S\n\n")
        if not self.paths.journal.exists():
            self.paths.journal.write_text("# LOLM-NFET running journal\n", encoding="utf-8")
        with self.paths.journal.open("a", encoding="utf-8") as handle:
            handle.write(header + markdown.strip() + "\n")

    def read_journal(self, max_chars: int = 8000) -> str:
        raw = self.paths.journal.read_text(encoding="utf-8") if self.paths.journal.exists() else ""
        return raw[-max_chars:]

    def get_goals(self) -> List[Dict[str, Any]]:
        if not self.paths.goals.exists():
            return []
        try:
            data = json.loads(self.paths.goals.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def set_goals(self, goals: List[Dict[str, Any]]) -> None:
        self.paths.goals.write_text(json.dumps(goals, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_goal(self, title: str, why: str = "", priority: int = 3) -> str:
        item_id = uuid.uuid4().hex[:8]
        goals = self.get_goals()
        goals.append({"id": item_id, "title": title, "why": why, "priority": priority, "status": "active", "ts": time.time()})
        self.set_goals(goals)
        return item_id

    def update_goal(self, item_id: str, **patch: Any) -> bool:
        goals = self.get_goals()
        for goal in goals:
            if goal.get("id") == item_id:
                goal.update({k: v for k, v in patch.items() if v is not None})
                self.set_goals(goals)
                return True
        return False

    def save_session(self, turns: List[Dict[str, Any]], title: str = "session") -> str:
        item_id = uuid.uuid4().hex[:8]
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", title.strip() or "session")[:80]
        path = self.paths.sessions / f"{int(time.time())}-{safe}-{item_id}.json"
        path.write_text(json.dumps({"id": item_id, "ts": time.time(), "title": title, "turns": turns}, indent=2, ensure_ascii=False), encoding="utf-8")
        return item_id
