-- Qira Proof V14: private R2 deliverables and single-use email challenges.
-- A deliverable can only be released by an authenticated Cloudflare operator
-- after independent human review, upload verification and signed-off delivery.
CREATE TABLE IF NOT EXISTS qira_deliverables(
 session_id TEXT PRIMARY KEY REFERENCES qira_orders(session_id),
 object_key TEXT NOT NULL UNIQUE,
 file_name TEXT NOT NULL,
 media_type TEXT NOT NULL CHECK(media_type IN ('application/pdf','text/html','application/json')),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 byte_length INTEGER NOT NULL CHECK(byte_length BETWEEN 1 AND 10485760),
 approved_at INTEGER NOT NULL,
 released_at INTEGER NOT NULL,
 revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS qira_deliverables_release_idx ON qira_deliverables(released_at,revoked_at);
CREATE TABLE IF NOT EXISTS qira_report_challenges(
 session_id TEXT PRIMARY KEY REFERENCES qira_orders(session_id),
 otp_digest TEXT NOT NULL CHECK(length(otp_digest)=64),
 expires_at INTEGER NOT NULL,
 sent_at INTEGER NOT NULL,
 send_window INTEGER NOT NULL,
 send_count INTEGER NOT NULL DEFAULT 1 CHECK(send_count BETWEEN 0 AND 3),
 failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count BETWEEN 0 AND 5),
 consumed_at INTEGER
);
CREATE INDEX IF NOT EXISTS qira_report_challenges_expiry_idx ON qira_report_challenges(expires_at);
