# Qira Proof V10 — Live Trend checkout, verified intake and all-route UX

Date: November 16, 2026  
Public product: https://proof.imagineqira.com/  
Checkout: https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07  
Draft code PR: https://github.com/TheArtOfSound/lolm/pull/71  
Source release: \`c5171c3a8e2a18875d885ed4e70dbbf203e31bbb\`  
CI: https://github.com/TheArtOfSound/lolm/actions/runs/43960853853  
Cloudflare Worker: \`qira-proof-commercial\`  
Worker release: \`c856aa28-266e-40fd-9317-ace1ac6ae2d4\` (100% production traffic)

## Product and payment surface

The **existing** Trend live Stripe merchant \`acct_1TdqpyGz3eX0vCtE\` is used; other merchant accounts and Trend integrations are untouched.

- Product: \`prod_Vdd7FJ2Ob210UH\` — Qira Proof Founding Workflow Review, $299 USD one-time, Stripe consulting service tax code \`txcd_20060048\`.
- Existing Payment Link: \`plink_1UcLsTGz3eX0vCtEVB7vSsQI\`, URL https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07, remains active and has Stripe automatic tax enabled.
- New **post-payment redirect**: \`https://proof.imagineqira.com/start-review?session_id={CHECKOUT_SESSION_ID}\`, with the placeholder replaced by Stripe after purchase. The Checkout Session ID is a reference, **not** proof of payment or customer authentication.
- New Stripe **live, enabled** snapshot webhook destination \`we_1UcXCyGz3eX0vCtEsYm87VFp\`, URL \`https://proof.imagineqira.com/api/stripe/webhook\` listening for:
  - \`checkout.session.completed\`
  - \`checkout.session.async_payment_succeeded\`
  - \`checkout.session.async_payment_failed\`
- The previous disabled Qira endpoint \`we_1UcMjVGz3eX0vCtENBLvl20a\` remains disabled. Existing unrelated Trend webhook destinations remain unchanged.
- A fresh endpoint signing secret was passed directly into a protected Cloudflare Worker secret binding, **without logging or copying the secret into repository source**. A separate random, protected HMAC key for buyer-email digest matching was also generated securely.

The existing Stripe Tax configuration does **not** establish tax registration coverage. Tax is enabled for the Trend merchant, and registrations must still be maintained as required by applicable jurisdictions.

## Production Cloudflare resources

Worker \`qira-proof-commercial\` has only these expected bindings:

| Name | Type | Purpose |
|---|---|---|
| \`QIRA_PROOF_CHECKOUT_URL\` | \`plain_text\` | Exact existing Stripe-hosted purchase URL |
| \`QIRA_PROOF_ORDERS\` | \`d1\` | Isolated Qira Proof payment-status and intake ledger |
| \`QIRA_STRIPE_WEBHOOK_SECRET\` | \`secret_text\` | Verify raw Stripe webhook payload HMAC with 300-second timestamp tolerance |
| \`QIRA_ORDER_EMAIL_PEPPER\` | \`secret_text\` | HMAC-SHA256 keyed checkout-email match without storing Stripe buyer email in the order table |

D1 database ID \`8554f204-0b7b-4c15-8307-4786c8443cf3\`.

Tables:
- \`qira_events\`: minimal Stripe event ID/type/time deduplication metadata.
- \`qira_orders\`: session ID, expected product/link/currency/amount, state, payment intent reference, paid time and a keyed \`buyer_email_digest\`. No card details or raw webhook body stored.
- \`qira_intakes\`: submitted checkout email, owner/repository name, submitted time, and one of \`awaiting_authorization\`, \`authorized\`, \`in_review\`, \`delivered\`, \`cancelled\`. This intake data is stored only when a paid buyer intentionally submits their repository request.

Daily \`17 3 * * *\` UTC Cloudflare Worker schedule now deletes old event, order, and intake rows after **180 days**, not accounting data at Stripe.

### Staff operating procedure

Access the secure Cloudflare D1 database with the account's administrative access (never expose the DB to public queries). To find new work:

\`\`\`sql
SELECT i.submitted_at, i.state, i.repository, i.contact_email
FROM qira_intakes i
WHERE i.state = 'awaiting_authorization'
ORDER BY i.submitted_at ASC
LIMIT 50;
\`\`\`

The contact email is *restricted customer PII* and should be used only for fulfilling the purchased review; avoid exposing it in general site telemetry, public repositories or support ticket URLs. Confirm customer identity and **read-only repository authorization** before collecting workflow evidence. Agree the delivery scope and time and send the final review manually. Never unlock a report solely from a Checkout Session ID.

To inspect counts without reading customer PII:

\`\`\`sql
SELECT status, COUNT(*) AS count FROM qira_orders GROUP BY status;
SELECT state, COUNT(*) AS count FROM qira_intakes GROUP BY state;
\`\`\`

The new paid-order path receives repository details automatically, but **staff notifications are not automated yet**: Cloudflare Email Routing for the main domain is disabled/unconfigured, and the ChatGPT hourly automation attempt was rejected due to an existing scheduled-task limit. Staff must check the D1 queue, or separately set up a verified operational alert. Do not assume a new customer request generates an email to the operator.

## End-to-end flow

1. Visitor enters a GitHub owner/repository URL on the homepage; validation occurs locally with no GitHub fetch, no automatic scan and no repository-data transmission.
2. Visitor opens the exact Trend-hosted $299 Stripe Payment Link.
3. Stripe redirects with the Checkout Session ID. In parallel, a genuine **Stripe-signed** successful payment event is processed by the Worker and recorded in D1 only when the Payment Link, live mode, $299 total and USD currency all match. An asynchronous pending status never counts as paid.
4. After a paid event is recorded, the intake page can render a “Stripe payment received” banner. A private paid-intake form only becomes available when the signed event includes a checkout email from which a protected digest was created.
5. The buyer enters their checkout email and GitHub owner/repo and submits through \`POST /api/orders/intake\`, protected by strict validation, 4 KB bounded JSON payload and the matching buyer-email digest. Unmatched, unpaid, stale or malformed attempts are rejected. No passwords, tokens or customer source files are accepted.
6. The submission inserts a single row into \`qira_intakes\` with \`awaiting_authorization\`. Repeated attempts for the same paid session do not silently replace the existing repository.
7. After submission, the buyer sees **“Your request is in.”** on the original session landing page. No further payment is needed. Qira must confirm authorization and manually deliver the report.
8. If Stripe has not yet delivered a matching paid event, the page shows a pending/unavailable state, warns against double purchase, and retains the existing manual receipt/email support fallback.

This remains a **human-reviewed consulting deliverable**, not an automated security certification, continuous SaaS subscription or assurance that any entered repository is safe.

## All public routes — cohesive V10 visual and interaction system

The standalone homepage was not the only redesigned surface. V10 shares navigation, editorial type scale, subdued color palette, reduced-motion styles, accessible focus and mobile behavior across:

1. \`/\` — local-first repository entry and $299 checkout
2. \`/case-study\` — pinned real source evidence, compact summary and findings jumps
3. \`/sample-report\` — synthetic, explicitly labeled report with working finding switcher
4. \`/methodology\` — review protocol with table of contents
5. \`/guides\` — field note index
6. \`/guides/github-actions-permissions\` — readable technical guide with section links
7. \`/guides/github-actions-dependency-pinning\` — same navigation
8. \`/guides/ssh-host-key-verification\` — same navigation
9. \`/guides/release-gate-failure-modes\` — same navigation
10. \`/privacy\` — actual new data handling, legal section navigation
11. \`/terms\` — revised human service/payment scope, legal section navigation
12. \`/start-review\` — manual fallback for unverified orders; paid buyer's verified online intake and received state

404 pages also provide useful recovery navigation. The search sitemap, robots, canonical metadata and noindexed sensitive intake state are preserved.

## Verification evidence, with limits

- Code CI run \`43960853853\`: **298/298 JavaScript tests + 19/19 Python** passed, including 6 new security/paid-intake tests, plus earlier signature verification, idempotency, D1 retention, privacy, SEO and interaction tests.
- Cloudflare isolated preview: same production application code, **separate temporary D1 and separate synthetic signing keys**. Signed **synthetic** event -> 200 webhook acceptance -> paid intake form -> buyer-email match -> direct D1 repository submission -> reload shows **“Your request is in.”** No real payment or Stripe provider delivery was generated. The temporary preview Worker, workers.dev subdomain and temporary test D1 database were deleted after the successful run.
- Real production Browser Rendering covered **all 12 routes** at 390px and 1280px — 24 route/viewport checks, no horizontal overflow, all HTTP 200, exactly one H1 and shared navigation/style. Interactive checks verified the sample finding switcher, guide TOC, case-study jumps and site navigation.
- Production \`/api/orders/health\` was 200 \`{"status":"ready"}\`.
- Production POST with an **invalid Stripe signature** yielded HTTP 400 \`invalid_signature\`. Production POST with an **unpaid/unknown session** yielded HTTP 403 \`payment_not_verified\`.
- Stripe readback confirmed the existing Payment Link remains active, the Checkout Session redirect includes \`{CHECKOUT_SESSION_ID}\`, automatic tax remains enabled, and the **new** webhook endpoint is enabled.
- Production database readback after rollout was 0 orders, 0 events, 0 intakes. Stripe Payment Link had two live but **unpaid/open** checkout sessions as of verification, so there was no prior paid order to backfill.

**Not yet proven:** A real customer's completed Stripe charge traversing Stripe's live webhook transport; operator notification delivery; an actual customer-authorized repository review; a completed human-delivered paid report; external independent accuracy adjudication; or compliance certification. Do not mislabel the synthetic smoke test as a real purchase.

## Release and rollback

- Production script name \`qira-proof-commercial\`, release version \`c856aa28-266e-40fd-9317-ace1ac6ae2d4\` at 100% traffic.
- Previous V9 version \`f3c5316d-cb94-4e89-8344-458289cea917\`; **do not roll it back without also reconciling the new active webhook and payment redirect**, as the former code had no direct intake route.
- Draft PR #71 should remain draft until the research scanner's separate independent accuracy and authentication gates are met; deploying the commercial frontend is not approval to merge the research branch.
- Do not remove/change the two protected secret bindings or adjust the shared Trend merchant's unrelated webhook endpoints during cleanup.

## Next production operator action

Review the D1 intake queue on a routine cadence. When the first genuine paid order is received, confirm the signed event, order row and intake row; check payment identity and repository authorization, agree a delivery time, and complete a source-linked human report. Add operational notification through an approved email provider or an available scheduled monitor; do not change the domain's MX just for this feature.
