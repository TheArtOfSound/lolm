# Qira Proof V13 — production operations and fulfillment gates

**Release:** November 16, 2026 Phoenix / November 17 UTC  
**Production:** https://proof.imagineqira.com/  
**Merchant:** Trend Stripe account `acct_1TdqpyGz3eX0vCtE`  
**Active offer:** $299 USD, one-time, tax inclusive, consulting code `txcd_20060048`  
**Checkout:** https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07  
**Worker:** `qira-proof-commercial` at 100% version `75cd991d-3d1d-4aaf-ac03-9155c7c950fa`  
**Order D1:** `qira-proof-orders-20261116` UUID `8554f204-0b7b-4c15-8307-4786c8443cf3`

## Production evidence

- **316/316 JavaScript tests and 19/19 Python tests** passed in [GitHub Actions 43986525288](https://github.com/TheArtOfSound/lolm/actions/runs/43986525288). The test suite covers signature validation, payment matching, partial refunds, full refunds, dispute closure, failed-refund holds, customer intake, outbox idempotency, provider retries and retention.
- The live Worker has **12 modules**. Existing D1, Stripe webhook signing, checkout URL and email digest bindings were preserved. A dedicated email provider key **has not been installed**.
- Cloudflare schedules: `*/5 * * * *` for notification queue retries and `17 3 * * *` for 180-day retention cleanup (all UTC). The paid-order event path remains the existing verified webhook.
- Trend Stripe event destination `we_1UcXCyGz3eX0vCtEsYm87VFp` is enabled for seven event types: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `charge.refunded`, `charge.dispute.created`, `charge.dispute.closed`, `refund.failed`.
- A **separate disposable D1** and temporary Worker were used for synthetic notification tests. A synthetic paid order, intake and partial-refund event produced three distinct pending notices, and running the queue again produced no duplicates. Those are **not production orders or sent emails**.
- Live browser inspection: all 12 public pages at 390px and 1280px (24 checks) showed one H1, no page-wide horizontal overflow and no missing in-page anchor targets. Supplemental DOM accessibility heuristics found no unlabeled buttons/inputs, duplicate IDs or missing image alternative attributes. External NVDA/VoiceOver validation is **not** established.
- Production D1 readback immediately after deployment: **zero orders, events, intakes, adjustments, or notifications**. No real paid charge, refund, dispute, human reviewed customer report or real provider email was generated during this release.

## Email notification activation: one protected settings action required

Resend has a verified sending domain `imagineqira.com`, and a **domain-restricted, sending-only key** named `Qira Proof Order Notifications 2026-11` was created. Automatic delivery is **not yet active**, because the attempted programmatic Cloudflare secret write was blocked. Do not retry by bypassing protected secret controls or putting the key in source code or plain-text bindings.

In Cloudflare, open **Workers & Pages → qira-proof-commercial → Settings → Variables and Secrets → Add**. Add the pre-created key as a **Secret** named `QIRA_RESEND_API_KEY`; value is held by the account owner in the key-creation result. Save/deploy the protected binding and verify that `https://proof.imagineqira.com/api/orders/health` returns `"notifications":"configured"` (it currently returns `"notifications":"awaiting_secret"`). Do not paste the credential into GitHub, tickets or public messages. The service sends from `Qira Proof Operations <notifications@imagineqira.com>` to the existing Qira operator mailbox.

After installation, the next five-minute cron attempts pending notifications automatically; provider non-2xx errors keep an item pending with exponential backoff. The outbox stores operational labels and order identifiers, **not customer emails or GitHub repository contents**. A provider acceptance receipt is not proof of inbox delivery. Confirm actual deliverability using a separately authorized controlled test; no production fake purchase is permitted.

Read-only queue inspection (run through authorized Cloudflare D1 admin only):

```sql
SELECT kind, status, COUNT(*) AS count
FROM qira_notifications
GROUP BY kind, status
ORDER BY kind, status;
```

```sql
SELECT kind, notification_id, status, attempts, datetime(created_at,'unixepoch') AS created_utc,
       datetime(next_attempt_at,'unixepoch') AS next_retry_utc
FROM qira_notifications
WHERE status <> 'sent'
ORDER BY created_at DESC
LIMIT 25;
```

## The human-verified fulfillment process

1. **Match the payment.** For each actual `qira_intakes.state='awaiting_authorization'` row, inspect the exact Checkout Session and PaymentIntent in Trend Stripe, including present refund, dispute and settlement state. D1 is a webhook ledger, not authoritative accounting.
2. **Confirm consent and scope.** Respond to the checkout email, agree on the single authorized repository, no more than 20 GitHub Actions workflow files, read-only installation/authorization procedure and specific delivery date. Do not ask the buyer to email passwords, PATs, SSH keys or source-code archives. The research GitHub App is a pilot and should not be represented as independently audited SaaS.
3. **Perform the review.** Pin immutable source references, collect configuration observations, corroborate each flagged item, document file and line, confidence, counterevidence, what was not proven and recommended remediation. Independent human signoff is required.
4. **Deliver and reconcile.** Send a secure final report and integrity receipt to the verified customer contact. Update `qira_intakes.state` only after the corresponding real authorization, start, final report delivery or cancellation event. Verify that no refund/dispute materialized before delivery. Record confirmation in the authorized business system—not a public PR.
5. **Handle exceptions.** A partial refund blocks paid intake but does not pretend the entire order was refunded. A full refund remains terminal. Dispute closure and failed refund events are recorded for manual review; do **not** auto-reactivate a disputed service merely because Stripe reported a win. Stripe remains the source of truth. Delayed reversal events that predate a Checkout event may not match the ephemeral Qira ledger and require manual Stripe reconciliation.

Read-only operator queue:

```sql
SELECT i.session_id,i.state,i.submitted_at,o.status AS payment_state,
       o.refund_amount,o.amount_total,o.currency
FROM qira_intakes i JOIN qira_orders o ON o.session_id=i.session_id
ORDER BY i.submitted_at DESC LIMIT 50;
```

Review of financial adjustments (no raw customer data in public release notes):

```sql
SELECT session_id,kind,amount_refunded,outcome,datetime(received_at,'unixepoch') AS received_utc
FROM qira_adjustments ORDER BY received_at DESC LIMIT 50;
```

Human authorization state advance, **only after actual identity + repo access verification**:

```sql
UPDATE qira_intakes SET state='authorized'
WHERE session_id='REPLACE_WITH_VERIFIED_SESSION'
AND state='awaiting_authorization'
AND EXISTS (
 SELECT 1 FROM qira_orders o WHERE o.session_id=qira_intakes.session_id
 AND o.status='paid' AND o.refund_amount=0
);
```

Do not execute the `authorized`, `in_review`, `delivered` or `cancelled` updates preemptively. For `delivered`, preserve the final report digest and the actual send/receipt evidence in the private customer record. Future automatic stage transitions require a separately reviewed, operator-authenticated interface.

## Buyer communication templates

**Scope confirmation (after verified checkout and matched intake):**

> Subject: Qira Proof — authorize your workflow review  
> We received the $299 Qira Proof review request for your selected repository. Before beginning, we will confirm your ownership or delegated authorization, the exact GitHub Actions workflow files in scope (up to 20), and a written delivery date. Please use our approved read-only GitHub authorization flow when instructed; do not send credentials, API tokens, or repository secrets by email. The review is a human-checked configuration assessment, not penetration testing or a security certification.

**Human-reviewed delivery (only after genuine completion):**

> Subject: Your Qira Proof review and evidence receipt  
> Your reviewed GitHub Actions configuration assessment for the agreed repository is ready. Secure report: [AUTHORIZED_LINK]. Evidence receipt and SHA-256: [ACTUAL_RECEIPT]. The report identifies the inspected workflows, source references, observations, uncertainty and prioritized next steps. Findings are not a guarantee that the repository is secure. Contact us if a source reference is incorrect or if you need clarification.

Never send templates with placeholder links or imply an uncompleted assessment is ready.

## Remaining external gates

- **Email credentials:** The protected Resend key installation is still required; Cloudflare declined the programmatic secret write. The five-minute queue is live but will not send without it.
- **Real transaction proof:** No authorized real customer payment, provider-to-production refund test or complete report delivery has occurred. Do not charge a customer account merely to generate a test; use an authorized purchase/test-mode flow and reconcile any resulting real obligations.
- **Repo authorization:** Only the customer or authorized GitHub organization owner can grant the relevant repository access. A connected GitHub API elsewhere in the workspace is not consent for this service.
- **Tax:** Trend Stripe Tax settings are active but there are **zero tax registrations**. Stripe Tax does not collect for a jurisdiction until the merchant records an applicable registration. Only register jurisdictions where the legal merchant has actually registered with tax authorities; do not infer registration from an Arizona address.
- **Independent security/accessibility review:** Live GitHub OAuth to a customer's organization, stateless session revocation risks, external scanner accuracy and actual screen-reader behavior remain human-validation gates. Keep the research/auth PR draft until they are independently verified.
