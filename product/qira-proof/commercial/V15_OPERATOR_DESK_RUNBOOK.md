# Qira Proof V15+ — protected fulfillment operations

## Production releases verified

- **Storefront:** https://proof.imagineqira.com
- **Commercial Worker:** `qira-proof-commercial`
- **Dedicated D1:** `qira-proof-orders-20261116` UUID `8554f204-0b7b-4c15-8307-4786c8443cf3`
- **Private R2:** `qira-proof-deliverables`, bound as `QIRA_PROOF_REPORTS`, no `r2.dev` or custom public domain
- **Trend Stripe:** signed webhook with seven payment, refund and dispute events; $299 Checkout link remains unchanged
- **Resend notifications:** protected sender configured on commercial Worker; 5-minute durable notification cron
- **V15:** reference-safe 180-day D1 cleanup, updated privacy/terms and R2 retention disclosures
- **V15.2:** out-of-order signed Stripe refund/dispute buffer, hashed with the protected payment email pepper, reconciled atomically when matched Qira Checkout arrives. 30-day temporary marker cleanup. The operator should still verify the **current** transaction in Stripe before releasing a report.

## Private operator console status

**SOURCE CODE IMPLEMENTED AND TESTED; NOT LIVE.** The deployment attempt for an additional management Worker was blocked by the connected Cloudflare tool's safety protections. This was **not** bypassed. Do not publish the hostname without verified Cloudflare Access enforcement.

- Source: [`operator_desk.mjs`](./operator_desk.mjs)
- Independent tests: `tests/commercial_operator_access.test.mjs`, `tests/commercial_operator_desk.test.mjs` (in the parent `tests` directory)
- Cloudflare Access application created:
  - Name: **Qira Proof — Private Operator Desk**
  - App ID: `36b136b5-dfae-40fd-9cfd-d5e18a212765`
  - Hostname: `ops.proof.imagineqira.com`
  - JWT audience: `5eed11519698f9a252e6558f5edbcbcc46534369b7b3ccbc167e439774e56fa3`
  - IdP: existing Access one-time email code
  - Policy: allow the Cloudflare account owner's verified email only (not everyone, not bypass)
- **The hostname is not currently routed** to any Worker. The public storefront has no operator-upload endpoint.

## Required protected deployment steps

Only when the Cloudflare account owner deliberately proceeds using Cloudflare's approved deployment interface, or a later approved tool is available:

1. Confirm that the Access app still allows *only* the intended owner, uses valid one-time login and protects the exact hostname. Test a non-allowlisted user and verify denial.
2. Publish the reviewed `operator_desk.mjs` entrypoint as a **separate** Worker named `qira-proof-operator`. Do not merge its code into the public `qira-proof-commercial` Worker or change the Stripe webhook route.
3. Configure only these Worker bindings:
   - `QIRA_PROOF_ORDERS` — D1, ID `8554f204-0b7b-4c15-8307-4786c8443cf3`.
   - `QIRA_PROOF_REPORTS` — R2 bucket `qira-proof-deliverables`.
   - `QIRA_PROOF_OPS_AUD` — text: `5eed11519698f9a252e6558f5edbcbcc46534369b7b3ccbc167e439774e56fa3`.
   - `QIRA_PROOF_OPS_EMAIL` — text: the exact allowlisted Cloudflare owner login.
   - **Do not** bind Stripe signing secrets, payment pepper, Resend API keys or unrelated R2 buckets to the operator Worker.
4. **Disable `workers.dev` public routes and preview subdomains.** Bind the Worker only to `ops.proof.imagineqira.com` after its Access protection is verified. The Worker itself independently verifies the Cloudflare Access JWT (RS256 signature against the Access organization's JWKS, issuer, audience, email, expiration, signed-in identity, and hostname).
5. Verify unauthenticated, wrong-host and non-allowlisted access is denied before using any customer records. Run one authorized owner-login smoke test, reviewing the queue read-only before touching data.
6. The audit table `qira_operator_audit` is already migrated in production. It records opaque Access principal ID, checkout session, action, reference, and time. Audit entries are transactionally paired with authorization, review-state, release and revocation actions.

**Do not issue actual report approvals to probe the UI.** A real customer must first pay, submit intake, provide lawful repository access and receive a human-reviewed document.

## Actual operator workflow when customer orders exist

1. Verify payment status in the Trend Stripe dashboard, including open refunds, partial refunds, disputes and payment-intent match.
2. Confirm customer ownership or delegated permission and read-only repository scope. Mark the request `authorized` only after verification; record the attestation.
3. Agree on scope and delivery date. Mark `in_review` only when ready. No private code may be collected without authorization.
4. Produce the actual evidence-backed assessment (up to 20 workflow files), inspect source-commit references, and approve it after human verification. A report is **not a penetration-test certificate**.
5. Upload the approved PDF via the protected operator workflow when it is deployed. The service checks 1–10 MiB, PDF signature/footer, SHA-256 digest, new immutable R2 key and paid, unreversed order. It records the release, moves intake to `delivered`, and logs operator approval.
6. A scheduled outbox sends a report-ready notice to the original verified checkout mailbox; the buyer downloads at https://proof.imagineqira.com/report-access after receiving a short-lived single-use email code. Never send a raw R2 URL.
7. To stop future downloads, revoke a release and write an audit reason. Prior downloads cannot be revoked retroactively.

## Existing operational access while the operator Worker is not deployable

**Cloudflare's authenticated dashboard/D1 admin remains the only authorized operator path.** Follow the previously committed [V14 manual report release guide](./V14_PRIVATE_R2_DELIVERY.md). Use its human verification and exact-match protections; avoid inserting fake paid orders or public file links.

Review private order queue safely:

```sql
SELECT o.session_id, o.status, o.refund_amount, i.state, i.repository,
 d.object_key, d.revoked_at
FROM qira_intakes i JOIN qira_orders o ON i.session_id=o.session_id
LEFT JOIN qira_deliverables d ON d.session_id=i.session_id
ORDER BY i.submitted_at DESC LIMIT 30;
```

Check transaction exceptions and early marker counts:

```sql
SELECT
 (SELECT COUNT(*) FROM qira_early_reversals) AS provisional_reversals,
 (SELECT COUNT(*) FROM qira_adjustments) AS matched_adjustments,
 (SELECT COUNT(*) FROM qira_customer_notices WHERE status='pending') AS pending_buyer_notices,
 (SELECT COUNT(*) FROM qira_notifications WHERE status='pending') AS pending_operator_notices;
```

No raw customer emails, report bodies, bearer tokens, Access JWTs or payment credentials belong in GitHub tickets or public issue comments.

## Genuinely outstanding validation and legal gates

- No genuine paid order/customer approval/full report delivery has yet been confirmed. Synthetic D1/R2 fixtures and CI pass results are not a substitute.
- Stripe automatic tax has zero registered tax jurisdictions. Only add registrations that legally exist; the merchant must perform or confirm jurisdictional registration.
- No independently performed screen-reader audit or independent security penetration test has been recorded.
- Resend provider acceptance may differ from final recipient inbox delivery. A consenting recipient's real notification test is required.
- Cloudflare Access owner-login end-to-end remains unverified until the protected operator Worker is actually deployed.
- The operator Worker code remains on the draft feature branch/PR and should not be marked as launched until these gates pass.

## Recovery and boundaries

Rollback a Worker version if a new production deployment breaks the public site, but remember **D1 and R2 state does not roll back with Worker code**. Keep additive migration files and do not delete storage or refund markers simply to make a previous Worker version boot. If the Stripe or Resend binding is missing, service should fail closed; do not re-create keys in source files.

The private R2 bucket must not have public domain or public listing enabled. When in doubt, withhold publishing rather than expose a report.
