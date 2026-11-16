# Qira Proof — Commercial front door, design system, and checkout

**Production site:** https://proof.imagineqira.com/  
**Research preview:** https://qira-proof-auth-lab-20261115.bryanleonard237.workers.dev/  
**Checkout:** https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07  
**Customer handoff:** https://proof.imagineqira.com/start-review

Last verified: November 16, 2026.

## Live configuration

| Component | Verified configuration |
| --- | --- |
| Marketing Worker | Cloudflare `qira-proof-commercial` at `proof.imagineqira.com` |
| Tracked code | `product/qira-proof/commercial/landing.mjs` |
| Stripe merchant | Trend — live account `acct_1TdqpyGz3eX0vCtE` |
| Stripe product | `prod_Vdd7FJ2Ob210UH`, **Qira Proof — Founding Workflow Review** |
| Stripe price | `price_1UcLrjGz3eX0vCtEC9Haqd02`, one-time **USD 299.00**, inclusive tax |
| Stripe product tax code | `txcd_20060048` — **Consulting Services** |
| Live payment link | `plink_1UcLsTGz3eX0vCtEVB7vSsQI` (active) |
| Payment tax | `automatic_tax.enabled=true`; liability: `self` |
| Checkout inputs | Required billing address, email, payment method |
| Payment after completion | Redirect to `/start-review` |
| Merchant documents | Stripe customer and post-payment invoice creation configured |
| Worker config | `QIRA_PROOF_CHECKOUT_URL` `plain_text` binding; checkout URL is **not embedded** in static code |
| Commercial health | `/health` returns `checkout_configured:true` |

**Tax warning:** Stripe Tax settings are active but Trend currently has **zero tax registrations**. Stripe does not automatically collect a state or country's tax until an applicable registration is added. The $299 amount is inclusive; registering correctly and documenting tax obligations remains a business/compliance responsibility. Do not claim tax is collected everywhere, or that absence of a Stripe registration establishes exemption.

## What the customer buys

A **one-time, human-reviewed configuration assessment** of one authorized GitHub repository containing up to 20 GitHub Actions workflow files. Deliverables: source-linked observations, explicit coverage and uncertainty, a JSON integrity receipt, and a written prioritized action summary. This is *not* penetration testing, ongoing monitoring, source-code remediation, a certified audit, or a guarantee of security.

Payment links are generated and hosted by Stripe; Qira Proof's marketing Worker does not process card details or hold GitHub tokens.

## Visual system / V3

The storefront is a custom editorial investigation interface, not a generic dashboard template.

- **Evidence workspace:** semantic SVG of a workflow path, three observation-switch buttons, synchronized explanation, line reference and visible illustrative source excerpt.
- **Report specimen:** synthetic labeled customer-facing example with OBSERVED, SOURCE, NOT PROVEN and RECOMMENDED REVIEW fields.
- **Purchase ticket:** clear $299 one-time price, scope of work, live external Stripe checkout and merchant/tax disclosure.
- **Customer intake:** staged receipt verification → read-only repository consent → human-reviewed delivery, with a mailto CTA above the fold and another after the timeline.
- **Legal pages:** privacy, service scope, explicit tax behavior, refunds/service limits and human support.
- **Accessibility:** semantic landmarks, keyboard-native controls, focus-visible styles, live text state, reduced-motion rule, mobile layouts without external fonts/images/scripts.

The sample report and the workflow graph are **synthetic illustrations**. Do not display them as actual customer results.

## Fulfillment boundary

The Stripe payment link and redirect exist and can accept real purchases. However **the full paid customer journey has not been tested using a real charge**. The `/start-review` page is a public guide, **not** proof of payment and not a provisioned customer portal.

Required operational procedure for a paid customer:

1. Stripe sends a receipt; redirect sends the buyer to `/start-review`.
2. Buyer contacts `bryanleonard@imagineqira.com` from their purchase email and provides the Stripe receipt reference and optional repository identifier. Never request tokens or secrets by email.
3. Qira verifies the transaction in **Trend's live Stripe account** before committing work or providing protected report access.
4. Qira confirms timing, selected repository, scope and read-only GitHub access.
5. Complete the assessment, human review, coverage statement and report delivery. Record confirmation and support/refund outcome.

**No webhook-driven customer entitlement, CRM record, automatic report fulfillment, automatic delivery SLA, or paid end-to-end receipt verification is currently implemented.** Do not imply otherwise.

## Testing

- JS and Python suites run through the Qira Proof GitHub Actions workflow; relevant tests include `commercial_landing.test.mjs` and `commercial_atlas.test.mjs`.
- Visual and mobile checks were performed in real Cloudflare Browser Rendering at 1440px desktop and 320/390px phones, including the price ticket, report specimen, evidence atlas, and intake flow.
- Button-state tests exercise all three evidence tabs and ensure the dynamic source excerpt, source location and diagram labels remain synchronized.
- Stripe **live API read-back** confirmed correct product/price IDs, one fixed quantity, `tax_behavior=inclusive`, `automatic_tax.enabled=true`, billing address requirements, invoice creation and success redirect.
- A real browser loaded the Stripe-hosted checkout: **Pay Trend**, **$299.00**, Qira Proof product and payment fields. No charge was submitted.
- The live website's purchase CTA and `/health` were checked after configuring the Cloudflare binding, and post-purchase handoff route was opened without authenticating.

## Remaining launch and research gates

- Register Trend for applicable tax jurisdictions; confirm treatment of the Consulting Services tax code with qualified advice when needed.
- Test a small, authorized **real paid order** including receipt, invoice, refund/support handling and manual fulfillment.
- Independently adjudicate scanner accuracy claims; validate non-owner GitHub OAuth sessions and read-only permissions.
- Consider Stripe webhook-based fulfillment only when secure event verification, idempotency, consent and data retention are designed; do not mistake public redirect for payment verification.
- Qira Proof's GitHub **PR #71 remains draft**. The marketed human-reviewed service is separate from the non-certified research preview.

## V4 — interactive specimen and local-only paid intake (Nov 16, 2026)

Deployment: `qira-proof-commercial` Worker version `f5aa99f0-79fe-4dad-a469-133f148a0dd9`, serving 100% of public traffic. The live Stripe binding was retained.

- **Full report explorer:** `/sample-report` is a separate, visually distinctive editorial case-file screen with three strictly synthetic findings. Each has its own direct YAML observation, source reference, explicitly unproven claims, and human-review recommendation. It offers print support and keyboard navigation (arrows, Home, End); the page never describes sample facts as real scan output.
- **Live state accessibility:** the selected report's ordinal and a screen-reader live announcement change with each case; corresponding source lines, code text and recommendation stay synchronized. On narrow phones (320–420px), case controls stack vertically for legibility and the redundant nav link is suppressed.
- **Commercial conversion:** the landing page links directly to the report explorer in both the hero and evidence dossier; its verified `Buy founding review` action still links to the active Trend Stripe-hosted payment link.
- **Paid intake friction:** `/start-review` now provides a local-only receipt composer accepting checkout email, receipt reference, and optional owner/repository string. JavaScript builds a `mailto:` URL for the customer's email app, not a server POST. There is no upload, analytics beacon, live payment check, credential intake or entitlement created by this feature. Credentials-like strings and invalid repository paths are rejected in client-side checks. A direct mailto fallback remains available.
- **Testing:** CI [237/237 JavaScript and 19/19 Python tests](https://github.com/TheArtOfSound/lolm/actions/runs/43842187230); added `tests/commercial_experience.test.mjs` covering report selector correctness, keyboard controls, print, screen-reader case numbering, intake composer, suspicious inputs, responsive CSS and live checkout binding invariant.
- **Live browser QA:** `/sample-report` and `/start-review` verified with Cloudflare Browser Rendering. Actual desktop/390px/320px screenshots reviewed. The 320px design was changed after finding overly small report selectors; the follow-up screenshot confirmed stacked, readable controls.
- **Payment safeguards retained:** Cloudflare confirmed `QIRA_PROOF_CHECKOUT_URL` bound and deployment receiving 100% of traffic. Trend Stripe API confirmed payment link `plink_1UcLsTGz3eX0vCtEVB7vSsQI` remains live/active with automatic tax enabled and redirect to `/start-review`; commercial `/health` returned `checkout_configured:true`.
- **Still outstanding:** Independent real-user screen-reader testing, an actual authorized paid order-to-human-deliverable test (not performed), manual verification of receipts in Stripe, and applicable tax registrations. The marketing storefront has no webhook-triggered entitlement or automatic fulfillment. Security scanner PR #71 remains draft.

## V5 — signed payment verification foundation (not yet activated)


## Verified deployment and retention — November 16

- **Latest Worker release:** version \`0cee7068-6808-401a-9a98-84db9b076e27\`, deployed at 100% traffic. Contains two JS modules (\`landing.mjs\` and \`payments.mjs\`) plus the isolated D1 binding.
- **CI:** [251 passing JS tests and 19 passing Python tests](https://github.com/TheArtOfSound/lolm/actions/runs/43845960170), including 10 provider-signature/forgery/payment-state tests and four 180-day retention tests.
- **Retention:** scheduled trigger \`17 3 * * *\` (03:17 UTC daily) deletes stored Stripe event IDs and Checkout Session handles older than **180 days**. The database is not the accounting system of record.
- **Observed ledger state at release:** 0 events / 0 orders. No artificial Stripe event or real customer charge was injected.
- **Safety read-back:** Stripe endpoint \`we_1UcMjVGz3eX0vCtENBLvl20a\` **disabled** because the protected signing-secret binding has not been installed. \`/api/orders/health\` reports \`unconfigured\`. Public \`/health\` continues to report checkout configured, and the active $299 Stripe link is unchanged.
- **Deployment controls:** the missing secret MUST NOT be worked around by removing signature verification, accepting redirects as proof of payment, copying the secret into public source, or storing it in a plain-text binding.

## V6 — Human-directed visual system and service-first product page (November 16, 2026)

The previous oversized all-caps/neon dashboard landing was evaluated in actual desktop and phone screenshots and found to resemble generic AI-generated marketing collateral. It was replaced rather than embellished.

**Changes deployed**
- First screen now clearly states the human-reviewed GitHub Actions service, scope, limits, source of evidence, $299 one-time tax-inclusive price, read-only preview and sample deliverable.
- Replaced giant slogan, fluorescent palette, pseudo-SOC panel and rotated labels with restrained editorial typography, warm neutral surfaces, graphite navigation, minimal oxide accent and simple line-based review details.
- Moved the existing synthetic workflow demonstration **below the service description** instead of treating it like the real product; preserved its explicit illustrative disclaimers and stateful observation-to-source interaction.
- Revised process, written-report specimen, offer and FAQ copy to be specific, descriptive and non-hyperbolic.
- Reworked the sample-report screen to an editorial reference document; kept all three accessible case variants, source excerpts, limitations, state announcements, keyboard controls and print behavior.
- Removed staged/fake ticket language from paid intake. Mobile top navigation now contains the brand plus a single purchase action; manual receipt intake remains available.
- Explicitly did **not** insert fake testimonials, fake customer risk scores, fabricated case studies, or unverified scanner-accuracy claims.

**Verification**
- Source commit \`61f1715fb02098ad70e49f8c0f02d53fe354ff5b\`.
- Passing CI: [256 JavaScript + 19 Python tests](https://github.com/TheArtOfSound/lolm/actions/runs/43849641955), including five service-first visual-structure regressions and all payment ledger/security tests.
- Staged in a separate \`qira-proof-editorial-preview-20261116\` Worker, reviewed actual 1440px/390px page screenshots and pricing/report/intake panels, then promoted to production; staged public workers.dev access disabled afterward.
- Production Worker version \`43396913-7eac-46c1-8a67-173e7a592718\`, 100% traffic; production desktop and 390px phone browser captures confirmed the new hierarchy.
- Live browser checks confirmed homepage \`#buyLink\` still points to Trend Stripe \`https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07\`, /sample-report, /start-review, \`/health\` checkout_configured=true, and \`/api/orders/health\` unconfigured (the secret is still absent).
- Stripe read-back confirmed live Payment Link active, automatic tax enabled, redirect /start-review. D1 remains bound and 03:17 UTC daily 180-day retention schedule remains present. No real charge was performed.

**Not proven:** The update improves presentation and task clarity but is not an independently audited usability study, independently assessed accessibility certification, completed paid fulfillment, or independent security-accuracy adjudication. The Stripe webhook remains disabled until the secret is securely installed. This is a human-reviewed service, not an automatically verified customer portal.
