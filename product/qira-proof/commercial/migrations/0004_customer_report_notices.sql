-- V14.1: customer-facing report-ready email outbox.
-- No customer identifiers or report content in the notification row.
CREATE TABLE IF NOT EXISTS qira_customer_notices (
 session_id TEXT PRIMARY KEY REFERENCES qira_orders(session_id),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','accepted')),
 attempts INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL,
 next_attempt_at INTEGER NOT NULL,
 lease_until INTEGER,
 accepted_at INTEGER
);
CREATE INDEX IF NOT EXISTS qira_customer_notice_due_idx ON qira_customer_notices(status,next_attempt_at,created_at);
