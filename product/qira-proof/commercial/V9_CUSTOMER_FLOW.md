# Qira Proof V9 — task-first customer experience

Date: 2026-11-16
Production: https://proof.imagineqira.com/
Worker: \`qira-proof-commercial\`
Production Worker version: \`f3c5316d-cb94-4e89-8344-458289cea917\` (100% traffic)
Source commit: \`ebffa899af9d2b5928f685ed3f97903228dcf27c\`
CI: https://github.com/TheArtOfSound/lolm/actions/runs/43955711501

## Design goal
Replace a verbose security-marketing funnel with a task-first workflow: paste a GitHub repository URL, get immediate local address validation and a clear purchase handoff. This is a **paid human-reviewed workflow configuration service**, not an automated security agent; never imply a security scan or successful repository authentication just because a URL was entered.

## Customer-facing information architecture
1. **One opening task** — "Which repository should we review?" A labeled GitHub URL field and one Continue action, with a direct link for private repositories and an optional evidence case study.
2. **Immediate local feedback** — validated owner/repo address, explicit 20-workflow scope, clear notice that existence/access/scanning has NOT been confirmed, one link to the live Trend Stripe $299 checkout and one optional link to actual source evidence.
3. **Trust through actual evidence** — a compact pinned-commit LOLM workflow source observation with links and explicit limits, replacing the fabricated dashboard illustration on the homepage.
4. **Three-step service description** — repository, checkout/authorization, human-reviewed report.
5. **Single $299 checkout** — unchanged protected Stripe Payment Link; the offer is plainly one-time and tax-inclusive, with service scope and report links nearby.
6. **Post-purchase intake** — a simple three-field email composer for Stripe checkout email, receipt reference and optional validated owner/repo, prefilled from the browser tab's sessionStorage where possible.

The complete synthetic interactive example remains at \`/sample-report\`; the real source-linked review remains at \`/case-study\`. SEO metadata, sitemap, methodology and four guides remain available. This retains discoverability without making informational content an obstacle to the buying flow.

## Technical and privacy guarantees
- The client-side entry checks URL formatting only, with no external fetch, repository download, GitHub login or upload. There is no silent scan.
- It rejects unauthenticated HTTP, non-GitHub hosts, URL credentials, extra path segments, query parameters and malformed owner/repository names. Never insert untrusted repository text as HTML; the interface uses textContent.
- The normalized owner/repo string lives in sessionStorage for the current browser tab to prefill intake. It is not sent to Qira by entry field.
- Intake is explicitly non-entitling and noindexed. Payment is confirmed manually by checking Trend Stripe; the public redirect is not treated as proof of payment.
- A standalone GitHub App research preview remains separate. No false claim of background automation, API-powered scanning or automatically delivered findings.
- No changes were made to the Stripe product, price, automatic tax, payment link, D1 ledger or 180-day cleanup. Webhook remains disabled because the live signing secret has not been securely added.

## Test and visual evidence
- GitHub CI run \`43955711501\`: **292/292 JavaScript and 19/19 Python** tests passed.
- Browser screenshots captured from staged Worker for 1440px desktop home and 390px mobile home and paid intake.
- Live Playwright interaction (Cloudflare Browser Rendering) validated:
  - Entering \`https://github.com/TheArtOfSound/lolm\` produces immediate "Repository address ready" and the exact Stripe URL \`https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07\` without a charge.
  - Browser tab stores \`TheArtOfSound/lolm\` and prefills the optional intake repository field.
  - Invalid nested URL \`https://github.com/owner/repo/tree/main\` triggers an \`aria-invalid=true\` error, without a source scan or payment.
  - At mobile 390px, homepage and intake \`document.documentElement.scrollWidth=390\` (no horizontal overflow); purchase button visible.
  - Real case study, synthetic sample report, methodology, technical guides, sitemap and robots remain HTTP 200. Intake has \`noindex,follow\`.
- Cloudflare production settings readback: Stripe checkout binding present, D1 binding present, \`17 3 * * *\` daily retention schedule unchanged, ledger 0 events / 0 orders. Worker release \`f3c5316d-cb94-4e89-8344-458289cea917\` at 100%.
- Staging Worker subdomain disabled after rollout to avoid duplicate crawlable pages.

## What is still manual
A purchase still requires Stripe hosted checkout followed by the customer's manual email receipt handoff. Repository access authorization and a human-delivered report remain separate steps. No signed Stripe webhook was activated, no end-to-end actual paid customer delivery was demonstrated, and no production charge was made. This remaining **checkout-to-fulfillment friction** is the next priority; do not claim the flow is fully automated, not even after this redesign.

Research PR #71 remains draft. No independent third-party accuracy adjudication or external usability study was performed.
