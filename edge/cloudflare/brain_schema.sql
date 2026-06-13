-- LOLM-NFET cloud brain — shared persistent memory + conversation sessions.
-- D1 (SQLite) so it needs no Workers AI neurons: sessions and memory persist
-- and are queryable even when the generation quota is exhausted.

CREATE TABLE IF NOT EXISTS sessions (
  id          TEXT PRIMARY KEY,
  created_at  INTEGER NOT NULL,
  last_at     INTEGER NOT NULL,
  turn_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turns (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL,
  role        TEXT NOT NULL,          -- 'user' | 'assistant'
  content     TEXT NOT NULL,
  ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, ts);

-- The shared brain: durable things the agent has learned, gathered from every
-- conversation anyone has anywhere. `uses` lets the agent learn which memories
-- actually help (recall increments it) — the math/architecture made persistent.
CREATE TABLE IF NOT EXISTS memory (
  id              TEXT PRIMARY KEY,   -- sha256(text) for dedup
  text            TEXT NOT NULL,
  kind            TEXT NOT NULL,      -- 'learning' | 'fact' | 'identity'
  importance      INTEGER NOT NULL DEFAULT 3,
  source_session  TEXT,
  ts              INTEGER NOT NULL,
  uses            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory(kind, importance);
