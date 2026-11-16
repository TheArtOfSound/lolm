# Qira Proof commercial front door

**Domain:** https://proof.imagineqira.com/  
**Worker:** qira-proof-commercial  
**Tracked source:** product/qira-proof/commercial/landing.mjs  
**Offer:** $299 one-time human-reviewed founding configuration assessment, one authorized GitHub repository, up to 20 workflow files.

The commercial worker is separate from the protected research preview and does not accept GitHub OAuth callbacks or store payment details. The preview remains at its existing workers.dev origin until GitHub App registration, callback origin, auth state, and account access are independently tested on the branded hostname. Do not point the new domain to the OAuth Worker without migrating its origin configuration and GitHub callback.

## Checkout

The landing page is intentionally **not directly purchasable** until an approved merchant account has a matching **live Stripe payment link**. Existing connected Stripe accounts were "Trend" and "SmallBusinessFix.com"; the owner must choose which account is legally appropriate for this Qira Proof product. Do not infer the merchant from other product names.

1. On the chosen Stripe live account, create one one-time Qira Proof founding workflow review product, amount **29900 USD cents**. Avoid recurring billing or misleading automated security promises.
2. Create a live, active payment link to that price. Collect customer email and optionally a non-secret repository identifier. Never solicit API tokens or private keys via Stripe custom fields.
3. Set Worker plain-text variable \`QIRA_PROOF_CHECKOUT_URL\` to the exact Stripe-hosted payment link URL. The code rejects other hosts/protocols.
4. Verify the home page says **Buy founding review**, the \`/health\` field \`checkout_configured\` is true, checkout opens the correct account/amount, and payment receipts include a service contact.
5. Independently test the fulfillment pipeline: a real purchase, receipt email, authorized repository intake and human-reviewed deliverable. Do not claim automated entitlement provisioning or a completed sale based on a payment link alone.

Before Stripe setup the CTA is an actual \`mailto:\` request for secure checkout and the health endpoint returns \`checkout_configured:false\`. This is honest lead capture, **not** an instant purchase path.

## Quality gates

- Automated tests: \`node --test product/qira-proof/tests/commercial_landing.test.mjs\` (also included by the existing Qira Proof test glob).
- Verify live desktop/mobile and legal pages without active scripts or unauthenticated provider access.
- Confirm Stripe merchant ownership, pricing, support, fulfillment/refund process and business disclosures.
- Paid service is **not** a penetration test, vulnerability certification, code fix, continuous monitoring or attested GitHub security result.
- Qira Proof scanner PR #71 remains in draft pending external security/accuracy review; commercial offer must stay bounded and human-reviewed.
