-- Qira Proof V15.2: secure short-lived buffer for signed Stripe reversals that
-- may precede their Checkout Session event. Only an HMAC of a PaymentIntent
-- is stored, not its raw identifier, payer email, card or another Trend order.
CREATE TABLE IF NOT EXISTS qira_early_reversals(
 event_id TEXT PRIMARY KEY,
 intent_digest TEXT NOT NULL CHECK(length(intent_digest)=64),
 kind TEXT NOT NULL CHECK(kind IN ('refunded','disputed','partial_refund','dispute_closed','refund_failed')),
 amount_refunded INTEGER NOT NULL DEFAULT 0 CHECK(amount_refunded BETWEEN 0 AND 29900),
 outcome TEXT,
 event_created INTEGER NOT NULL,
 received_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS qira_early_reversals_intent_idx ON qira_early_reversals(intent_digest,received_at);
CREATE INDEX IF NOT EXISTS qira_early_reversals_ttl_idx ON qira_early_reversals(received_at);
-- Daily retention: delete rows more than 30 days old.
