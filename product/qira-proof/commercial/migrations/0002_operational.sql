-- Qira Proof V13 operational reliability: additive migrations only.
-- Applied to the dedicated production D1 after preflight; keep original four bindings.
ALTER TABLE qira_orders ADD COLUMN refund_amount INTEGER NOT NULL DEFAULT 0 CHECK(refund_amount BETWEEN 0 AND 29900);
CREATE TABLE IF NOT EXISTS qira_adjustments (
 event_id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('partial_refund','dispute_closed','refund_failed')),
 amount_refunded INTEGER NOT NULL DEFAULT 0,
 outcome TEXT,
 received_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS qira_adjustments_session_idx ON qira_adjustments(session_id,received_at);
CREATE TABLE IF NOT EXISTS qira_notifications (
 notification_id TEXT PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('paid','failed','refunded','disputed','intake','partial_refund','dispute_closed','refund_failed')),
 session_id TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent')),
 attempts INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL,
 next_attempt_at INTEGER NOT NULL,
 lease_until INTEGER,
 sent_at INTEGER
);
CREATE INDEX IF NOT EXISTS qira_notifications_delivery_idx ON qira_notifications(status,next_attempt_at,created_at);
