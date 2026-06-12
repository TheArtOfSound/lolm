-- lolm-brain (D1) — conversation sessions + memory provenance.
-- The vectors live in Vectorize (semantic recall); D1 is the verifiable
-- ledger: every turn of every conversation, and the origin + usage of every
-- memory the agent ever stored. Nothing is recalled that cannot be traced
-- back to the run that created it.

CREATE TABLE IF NOT EXISTS sessions (
  id          TEXT PRIMARY KEY,        -- opaque session token
  created_at  INTEGER NOT NULL,
  last_at     INTEGER NOT NULL,
  title       TEXT,
  turn_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turns (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL REFERENCES sessions(id),
  idx         INTEGER NOT NULL,        -- 0-based position within the session
  role        TEXT NOT NULL,           -- 'user' | 'assistant'
  content     TEXT NOT NULL,
  ts          INTEGER NOT NULL,
  run_id      TEXT,                    -- links an assistant turn to its agent run
  verdict     TEXT                     -- the run's proof verdict, for audit
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, idx);

-- Provenance ledger for the shared Vectorize memory bank. One row per stored
-- memory; the vector id matches the Vectorize id, so a recall can always be
-- explained: what it is, which run/session created it, and how often it has
-- helped since.
CREATE TABLE IF NOT EXISTS memories (
  id            TEXT PRIMARY KEY,      -- == Vectorize vector id
  text          TEXT NOT NULL,
  kind          TEXT NOT NULL,         -- 'fact' | 'self' | 'skill' | 'correction'
  created_at    INTEGER NOT NULL,
  source_session TEXT,
  source_run    TEXT,
  importance    INTEGER NOT NULL DEFAULT 3,
  recall_count  INTEGER NOT NULL DEFAULT 0,
  last_recalled INTEGER
);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_recall ON memories(recall_count DESC);
