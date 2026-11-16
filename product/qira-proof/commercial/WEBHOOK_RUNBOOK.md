# Qira Proof: signed order ledger / activation and validation

**State as of November 16, 2026:** payment-verification **code deployed**, **signing secret NOT configured**, Stripe webhook endpoint **disabled** to avoid live delivery failures. Existing live $299 payment link and manual fulfillment continue to work.

## Architecture

- Commercial Worker: \`qira-proof-commercial\` on \`https://proof.imagineqira.com\`.
- D1 database: \`qira-proof-orders-20261116\` (U.S. jurisdiction). Binding name: \`QIRA_PROOF_ORDERS\`.
- Webhook URL: \`https://proof.imagineqira.com/api/stripe/webhook\`.
- Stripe live account: **Trend**, only expected Qira Proof Payment Link ID \`plink_1UcLsTGz3eX0vCtEVB7vSsQI\`.
- Stripe webhook endpoint ID: \`we_1UcMjVGz3eX0vCtENBLvl20a\`, currently disabled pending setup.
- Signature environment binding: \`QIRA_STRIPE_WEBHOOK_SECRET\`, **secret_text**, absent until setup.
- Events to receive: \`checkout.session.completed\`, \`checkout.session.async_payment_succeeded\`, \`checkout.session.async_payment_failed\`.

## What the handler proves

The handler validates Stripe's raw payload against the HMAC-SHA256 signature with a five-minute delivery timestamp window. It bounds payload length, rejects test-mode and forged events, and accepts only the exact payment link, live Checkout Session, single-payment mode, USD, and $299 total. D1 batch writes a minimal event identifier and session status. Duplicate deliveries do not create duplicate orders. Pending or later failed events do not downgrade a previously paid event. D1 error returns 503 so Stripe can retry rather than falsely acknowledging the event.

A signed payment event confirms **event receipt**, not a human identity. Do not grant private report access using a Checkout Session ID from a URL. The public page may only display a minimal status with no personal details. Stripe Dashboard is still the operator's source of truth for disputes, refunds, chargebacks and actual fulfillment.

## Activation: secure manual secret setup

**Do not paste webhook signing secrets into chat, GitHub, email, issue comments, public site variables, or plain-text Worker bindings.**

1. In the **Trend** Stripe Dashboard, open **Workbench → Webhooks** (or **Developers → Webhooks**) and find endpoint ID \`we_1UcMjVGz3eX0vCtENBLvl20a\` matching the Qira Proof URL. Reveal its live signing secret via Stripe's protected UI.
2. In Cloudflare Dashboard, open **Workers & Pages → qira-proof-commercial → Settings → Variables and Secrets**, and add \`QIRA_STRIPE_WEBHOOK_SECRET\` as an **encrypted secret** value using Stripe's live \`whsec_\` value. Deploy the binding without changing \`QIRA_PROOF_CHECKOUT_URL\` or \`QIRA_PROOF_ORDERS\`.
3. Confirm \`/api/orders/health\` reports \`ready\` **only** after both the secret and D1 binding are present. It must report \`unconfigured\` otherwise.
4. In Trend's Stripe Dashboard, enable the matching webhook endpoint. Send a Stripe test event in a controlled development setup first. For live verification, check delivery response status and the D1 ledger after the first actual paid order.
5. After signed delivery is verified and event retention is configured, update the existing Payment Link redirect to \`https://proof.imagineqira.com/start-review?session_id={CHECKOUT_SESSION_ID}\` **only if the Stripe UI/API supports the placeholder for this Payment Link**. Do not alter the active checkout as an untested assumption. The live source already safely renders statuses for valid high-entropy Checkout Session IDs.
6. Confirm the customer return page shows paid status **only** when a signed paid event has been recorded. Failed, pending, or unavailable statuses must never grant access. Keep manual checkout-email and human repository-authorization checks.

## Strict limitations

- Existing Stripe live purchases continue via the active Qira Proof payment link; no secret is required to take payment.
- With webhook endpoint disabled, D1 remains empty and the return page does not auto-verify payments.
- No refund/dispute-state sync is yet implemented. Verify final order state in Trend Stripe before delivering or granting access. Never infer active entitlement from the mere existence of a past paid event.
- No email service, authenticated customer login, CRM workflow, report storage, webhook-triggered report generation or automatic customer entitlement exists.
- Tax registration/compliance remains separately outstanding; Stripe Tax is enabled but Trend had no tax registrations at last check.
- Source \`product/qira-proof/commercial/payments.mjs\` has automated signature, retry, replay, spoofed-link, amount/currency, failure/outage and customer-status tests. This is not a real Stripe event delivery test.
