# QIRA Proof — Release quality gates
Updated 2026-11-16. These are verification standards, not claims of certification.

## 0. Product boundary
QIRA Proof is an opt-in, read-only configuration-evidence review. It is **not**
a penetration test, assurance certification, exploit detector, source-code scanner,
or attested statement from GitHub/Cloudflare/Vercel. Never imply these.

## 1. Functionality and provenance
- [x] Owner completed real GitHub OAuth; one workflow review and a subsequent 20-of-20 workflow review were observed.
- [x] Workflow evidence tied to exact source commit, not mutable main branch.
- [x] Repository scan records `discovered`, `selected`, `assessed`, `skipped`, `truncated`, `complete`, and commit within the receipt.
- [x] New v2 receipts record analysis policy version; archived deterministic v1 receipts remain verifiable.
- [x] Report and JSON receipts clearly distinguish observed conditions from verified vulnerabilities.
- [x] Declared read-only permissions and privileged trigger context can be observed conservatively, with unsupported syntax producing unknown rather than safe.
- [ ] Build a reviewed 100-workflow fixture corpus spanning anchors, multiline scripts, reusable workflows, unusual permissions, GitHub policy variants, and adversarial YAML. Initial nested-permission and event-sequence adversarial fixtures are covered; the larger corpus and manual adjudication remain outstanding.
- [ ] Publish precision/recall and false-positive rates with explicit denominators and human adjudication.
- [ ] Independently corroborate every new rule against a pinned provider fixture and a second implementation.

### Real owner scan verification (November 16)

The owner supplied a successful live `TheArtOfSound/lolm` scan of 20/20 workflows at `f9700d2e661640da4a8d0cf2bb9c046d77f8a06b`: 109 source-linked facts, 27 review observations under two patterns, and 13 workflows with recognized read-only permission declarations. A separate authorized GitHub read corroborated those 13 actual root-level `contents: read` declarations. These are **syntactic observations**, not independently attested provider policy.

Latest improvement: the write authorization inventory now enumerates specific recognized scopes (for example `contents: write`, `issues: write`, and `id-token: write`) with exact source lines in v3 evidence receipts. It separately identifies ambiguous declarations without treating them as vulnerabilities. Both local and hosted scanners now refuse to classify nested `env` / `with` permission-shaped keys as effective GitHub permissions, and treat unsupported inline event YAML as unknown. The owner has **not yet run the new v3 exact-scope collector through the browser**.

### Exported owner report verification — November 16, 2026

The owner supplied an actual human-readable `qira-proof-configuration-review.html`
export (captured at `2026-11-16T07:12:48.579Z`) with 20/20 workflows at
`f9700d2e661640da4a8d0cf2bb9c046d77f8a06b`. The report enumerates 109
facts, 27 observations under two conditions, one branch-protection visibility
gap, 13 files with read-only permission declarations, and seven files with
12 declared write permission scopes.

Evidence overlap was verified by parsing the uploaded report:
- 3 workflow files: mutable action references + SSH host discovery + declared write scope
- 4 workflow files: mutable action references + declared write scope
- 5 workflow files: mutable action references + SSH host discovery
- 7 workflow files: mutable action references without the other two indicators
- 1 scanned workflow with none of those three conditions observed

A new non-scoring **Workflow review order** section presents these groups
with pinned source links in both the browser and printable export. This is a
review-efficiency tool, **not** a validated exploitability ranking or a change
to the SHA-256 receipt. The supplied HTML contains a digest but no companion
JSON; the digest cannot be independently recomputed from the HTML alone.

**Unmet gate:** owner must rerun the newest build and independently validate
the new print layout and scope-specific links. Professional security and
accessibility review and independent reviewer accuracy testing remain open.

## 2. Security and privacy
- [x] GitHub OAuth state, PKCE, callback validation, encrypted short-lived browser session, CSRF protection, server-only token exchange.
- [x] GitHub metadata GET and token POST explicitly reject redirects using Cloudflare-compatible manual mode.
- [x] No provider secrets in bundled static assets; protected Worker bindings maintained.
- [x] Bounded per-file reads, 20-file repository scan cap, partial-scan disclosure, no automatic fixes.
- [ ] Independently review GitHub App requested permissions, OAuth callback surface, session key rotation and cookie replay.
- [ ] Implement durable session revocation or short-lived provider token revocation. Today a cleared browser cookie does not invalidate a previously copied, unexpired encrypted cookie.
- [ ] Add abuse controls, request budget enforcement, basic rate limits, and per-request idempotency.
- [ ] Obtain professional security review before persistent tenant accounts or paid SaaS.
- [ ] Review privacy disclosures and retention with counsel before customer data onboarding.

## 3. Accessibility, UX and reliability
- [x] Searchable authorized repository list, with async response race protection.
- [x] Result keyboard tabs, visible focus, skip link, reduced-motion CSS, explicit labels.
- [x] Read-only report export and independent JSON verification.
- [ ] Run automated WCAG 2.2 AA accessibility scans and manual keyboard + screen-reader checks on mobile/desktop.
- [ ] Test the complete owner flow in Chrome, Firefox, Safari, Edge, iOS and Android.
- [ ] Test 320/375/390/768/1024/1440px layouts including 200% text zoom, high contrast and 400% zoom.
- [ ] Validate workflow selection, expiration, revoked install, private repo 403/404, network timeouts and large metadata.
- [ ] Add user-facing retry/recovery states and make scan scope/limits clear before starting.

## 4. Operations and delivery
- [x] GitHub CI runs Node + Python tests and syntax-checks the assembled Worker.
- [x] Cloudflare Worker isolated preview has been deployed with existing protected secrets preserved.
- [ ] Replace manual staging uploads with reproducible deployment tooling and per-release SHA verification against CI artifact.
- [ ] Add smoke tests for GitHub login and read-only assessment after each deploy, without automating user consent.
- [ ] Add production-grade observability with minimal, sanitized data; alert on failures without logging source or credentials.
- [ ] Document rollback, ownership, support path and incident response.

## 5. Commercialization
- [ ] Independent design-partner validation: two non-owner engineering teams and at least three representative reviews.
- [ ] Establish time-to-first-finding and time-to-remediation metrics.
- [ ] Validate buyer demand and willingness to pay before shipping subscriptions.
- [ ] Legal terms, payment, support expectations, refund handling and service-level boundaries.
- [ ] Protect the GitHub App permissions before wide customer installation.

**Gate:** Keep PR #71 draft and the preview labeled research until the outstanding
security, accessibility and non-owner validation gates are met. A passing CI job
does not satisfy them.
