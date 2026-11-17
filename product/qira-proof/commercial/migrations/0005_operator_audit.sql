-- V15.1 private operator audit ledger.
-- Cloudflare Access JWT must be verified on every operator request before D1/R2 access.
-- Actor sub is a Cloudflare Access opaque identity, not an email or bearer token.
CREATE TABLE IF NOT EXISTS qira_operator_audit(
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL,
 actor_sub TEXT NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('authorize','begin','publish','revoke')),
 detail TEXT NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS qira_operator_audit_timeline ON qira_operator_audit(created_at DESC);
CREATE INDEX IF NOT EXISTS qira_operator_audit_order ON qira_operator_audit(session_id,created_at);
