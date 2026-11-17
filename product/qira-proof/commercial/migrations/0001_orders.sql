-- Qira Proof isolated D1 minimal Stripe event ledger.
-- Created in US jurisdiction on 2026-11-16.
-- No buyer emails, receipt bodies, card numbers, GitHub tokens, or raw Stripe
-- events are stored. Retention/purge schedule must be separately established.
CREATE TABLE IF NOT EXISTS qira_events (
 event_id TEXT PRIMARY KEY,
 event_type TEXT NOT NULL,
 event_created INTEGER NOT NULL,
 received_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS qira_orders (
 session_id TEXT PRIMARY KEY,
 payment_link TEXT NOT NULL,
 payment_intent_id TEXT,
 status TEXT NOT NULL CHECK(status IN ('pending','paid','failed','refunded','disputed')),
 amount_total INTEGER NOT NULL,
 currency TEXT NOT NULL,
 event_created INTEGER NOT NULL,
 paid_at INTEGER,
 updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS qira_orders_payment_intent_idx ON qira_orders(payment_intent_id);
CREATE INDEX IF NOT EXISTS qira_orders_status_idx ON qira_orders(status,updated_at);
