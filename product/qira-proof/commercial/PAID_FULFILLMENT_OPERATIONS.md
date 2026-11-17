# Qira Proof — live Trend checkout and human-review fulfillment operations

**Production:** https://proof.imagineqira.com/  
**Merchant:** Trend (existing live Stripe account)  
**Founding service:** $299 USD, one-time, tax-inclusive, GitHub Actions configuration review  
**Intake:** https://proof.imagineqira.com/start-review  
**Stripe payment link:** https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07

This is a paid, human-reviewed service. Stripe signature validation, paid intake, refund/dispute tracking and a durable notification queue are live. **Outbound operator email remains disabled until the protected Resend key is installed.** No production test charge or completed customer report delivery occurred. Current implementation: [V13 operations release](./V13_OPERATIONS_RELEASE.md).

## Payment components already in production

| Component | Configured state |
| --- | --- |
| Stripe product | \`prod_Vdd7FJ2Ob210UH\` — active; Consulting Services tax code \`txcd_20060048\` |
| Stripe one-time price | \`price_1UcLrjGz3eX0vCtEC9Haqd02\` — USD 29,900 cents, inclusive tax behavior |
| Payment Link | \`plink_1UcLsTGz3eX0vCtEVB7vSsQI\` — active; automatic tax enabled |
| Redirect | \`https://proof.imagineqira.com/start-review?session_id={CHECKOUT_SESSION_ID}\` |
| Webhook | \`we_1UcXCyGz3eX0vCtEsYm87VFp\` — enabled at \`/api/stripe/webhook\` |
| Webhook event types | Checkout success/failure, charge refunds, dispute creation/closure and refund failure — seven enabled types |
| Cloudflare secrets | \`QIRA_STRIPE_WEBHOOK_SECRET\`, \`QIRA_ORDER_EMAIL_PEPPER\` configured, do not expose |
| Ledger | D1 binding \`QIRA_PROOF_ORDERS\`, database \`8554f204-0b7b-4c15-8307-4786c8443cf3\` |
| Retention | \`17 3 * * *\` UTC cleanup schedule; 180-day ephemeral ledger retention |

A duplicate product, Price, Payment Link, or additional Stripe account is **not needed**. Never move Qira Proof payments into another shared account without explicitly reconciling existing links, taxes and refunds.

## What the customer experiences

1. Customer enters a GitHub \`owner/repository\` address on the homepage. This validates syntax only, without accessing GitHub or storing content on the server.
2. Customer purchases the one-time assessment at hosted Stripe checkout. Stripe, not the Worker, collects payment data.
3. Stripe redirects the browser with a Checkout Session ID. A redirect **alone does not establish payment**.
4. The Worker checks its ledger of previously verified, HMAC-signed Stripe events for that session. A completed/paid session matching the exact Qira Proof Payment Link, total and currency receives a \`paid\` state.
5. If a paid session has a hashed checkout email attached, the buyer can submit the checkout email and repository into the verified same-origin \`/api/orders/intake\` form. The checkout email is HMAC-matched to the digest stored from the signed webhook. The accepted intake has state \`awaiting_authorization\` and is idempotent on session ID.
6. For pending events, Stripe delays, or unavailable verification, the site must not grant access and should instruct the customer to check their Stripe receipt or contact Qira. **Do not invite the buyer to pay twice solely because the status is pending**.
7. Qira verifies identity and repository authorization before human assessment and delivery. The paid intake does not automatically scan the repository or release private findings.

## V12 production — refund and dispute reconciliation (November 16, 2026)

- Cloudflare Worker `qira-proof-commercial` deployed at **100%** on Worker version `6a5875f8-d702-497b-b684-7e91e2ff0124`, after an isolated 12-route browser preview. All four original bindings remain: live checkout URL, two protected secret bindings and the original restricted D1 database.
- The **existing** Trend Stripe event destination `we_1UcXCyGz3eX0vCtEsYm87VFp` is enabled for five events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `charge.refunded` and `charge.dispute.created`. The previously disabled destination and all unrelated Trend apps were left unchanged.
- Every event must pass Stripe HMAC verification. A full-refund or dispute event must match **the saved PaymentIntent ID** from a verified Qira Proof checkout, with live mode, USD currency and $299 amount; unrelated Trend products cannot change Qira order status. Replayed checkout-success events cannot reactivate an already `refunded` or `disputed` order.
- A buyer opening the return route with the affected Checkout Session sees a refund or dispute status instead of a verified paid-order intake. The intake API accepts only `paid` orders, so reversal states cannot submit new intakes.
- Latest feature-branch CI: [310 passing JS tests, 0 failed](https://github.com/TheArtOfSound/lolm/actions/runs/43983254765), plus a successful Python test job. Post-deploy production browser rendering checked all 12 public routes at **390px and 1280px**: no page-wide horizontal overflow, missing same-page hash anchors or extra/missing primary headings in these 24 checks.
- Live D1 had **0 orders, 0 signed payment events, 0 intakes** at latest read. No real paid checkout, refund or dispute has validated Stripe-to-Worker delivery. **Synthetic signed events belong in staging only.**

**Manual reconciliation is still required:** partial refunds; refunds/disputes delivered before their original Checkout event; resolved/closed disputes; failed refunds; cross-account/bank reconciliation; changing existing intake state; notifying the operator and refund evidence submissions. Stripe is authoritative, not this short-lived D1 status ledger. Do not infer a refund's settlement or a dispute's final result from the status label alone.

For a buyer with a reported reversal, review the *exact* PaymentIntent in the Trend Stripe Dashboard, confirm the current refund/dispute disposition and any already started/delivered service, then follow the applicable support and cancellation policy. Do not automatically resume work or issue a second charge to recover from a reversal notification.

## Operations when a paid order arrives

- In the Trend Stripe Dashboard, verify the payment, current amount, refund/dispute status, customer identity and applicable tax treatment for the **specific** Checkout Session.
- Inspect the Cloudflare D1 \`qira_orders\` and \`qira_intakes\` tables for new, matched \`paid\` and \`awaiting_authorization\` records. These tables contain customer contact email and repository names; only authorized operators should access them.
- Agree on repository scope, count of workflow files (up to 20), access method and delivery timing. Never request GitHub passwords or tokens by email.
- Obtain repository authorization through the read-only GitHub App workflow where applicable; do not treat a public repository name as private access permission.
- Use a pinned source snapshot to prepare the report. Each item needs a precise file/line citation, what was observed, what was not proven, a suggested review/remediation and a coverage statement.
- Review the report with a human before sending it. Provide a secure final deliverable and confirm receipt through the checkout email/contact channel.
- Update the intake state to \`authorized\`, \`in_review\`, \`delivered\` or \`cancelled\` after the corresponding real action, not in anticipation.

Example **read-only** operator query in Cloudflare D1 (avoid logging or sharing raw emails in public PR comments):

\`\`\`sql
SELECT
  i.session_id,
  i.state,
  i.submitted_at,
  o.status AS stripe_event_status,
  o.amount_total,
  o.currency
FROM qira_intakes AS i
JOIN qira_orders AS o ON o.session_id=i.session_id
ORDER BY i.submitted_at DESC
LIMIT 50;
\`\`\`

The Stripe Dashboard is the authoritative accounting source. D1 status is a bounded **webhook receipt ledger**, not a complete refund/dispute accounting system. The endpoint also subscribes to refund and dispute events, but late/out-of-order events and final outcomes still require an independent current Stripe Dashboard check. Do **not** infer payment is still valid solely because D1 previously recorded \`paid\`.

## Safety and failure behaviors

- Signed webhook required: \`stripe-signature\`, fresh timestamp and protected secret. Never emulate a paid event in production or store raw event JSON, billing details, card data, tokens or secrets.
- Accept only the configured live Payment Link, \`$299.00\` total and \`usd\` currency. Reject mismatches and asynchronous transactions that are not yet paid.
- An email-address claim alone does not prove customer identity; checkout email must match the signed event's digest, and repository authorization is separate.
- The public session-ID status is not customer authentication; it may return a limited pending/paid state without exposing buyer data or private reports.
- The website's \`/start-review\` is \`noindex\`, \`no-store\` and \`no-referrer\`. Session IDs are not included in SEO canonical or social metadata.
- DB errors should surface an unavailable state so Stripe retries rather than silently accepting an unrecorded payment.
- Exact production charge/fulfillment remains unproven until a real buyer places an order. This runbook does not constitute that proof.

## Unfinished operational automation (do not overclaim)

The signed webhook, protected intake, D1 notification queue, five-minute retry cron and cleanup are active. **Actual operator email awaits the protected Resend secret.** Human verification of Stripe state, repository authorization, review and report delivery remains necessary.

Use the restricted Cloudflare D1 query interface for the operator queue until a properly authenticated dashboard has been independently reviewed. See V13 operations release for activation and evidence.
