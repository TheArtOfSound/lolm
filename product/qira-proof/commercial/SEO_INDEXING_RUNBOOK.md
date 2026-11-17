# Qira Proof — SEO, discovery, and indexing release V8

**Date:** 2026-11-16  
**Canonical host:** https://proof.imagineqira.com/  
**Live commercial Worker:** \`qira-proof-commercial\` version \`f772e00e-503f-4433-9179-76982dd4f351\` at 100% traffic  
**Source SHA:** \`5ef98134063bc4f07abb92ea61edc1eba9c45351\` on draft PR #71

## Production technical SEO

The previous marketing Worker used a single generic description and no canonical links, per-page Open Graph/Twitter metadata, structured data, sitemap or robots.txt. V8 introduces:

- Distinct human-authored titles and descriptions for each public route; one canonical absolute URL per indexable page.
- Open Graph and Twitter summary-card fields, with consistent canonical URL and no invented OG preview image.
- JSON-LD: Organization and WebSite for the home page, Service and a truthful $299 one-time Offer, TechArticle for the real case study and original technical guides, and BreadcrumbList on child pages. **No fabricated ratings, testimonials, clients or security certifications**.
- An absolute-URL XML sitemap at \`/sitemap.xml\` with 9 publicly useful canonical pages and truthful \`2026-11-16\` publication/update date.
- \`/robots.txt\` with \`Sitemap: https://proof.imagineqira.com/sitemap.xml\`, public-path crawl allowance and \`Disallow: /api/\`.
- Explicit \`noindex,follow\` (HTML and HTTP header) on \`/start-review\`. The canonical/OG URLs omit \`session_id\` and all purchase references. The intake and public responses never treat a redirect as paid entitlement.
- 308 canonical redirects for trailing-slash duplicates. Unknown routes return 404 with a noindex header.
- An IndexNow public proof file at \`/e785fc5185dd625186e79d5e9a5b53d3.txt\`, served as text/plain, noindex, which is required before **a participating search engine can validate a submission**.

### Canonical sitemap URLs

1. https://proof.imagineqira.com/
2. https://proof.imagineqira.com/case-study
3. https://proof.imagineqira.com/sample-report
4. https://proof.imagineqira.com/methodology
5. https://proof.imagineqira.com/guides
6. https://proof.imagineqira.com/guides/github-actions-permissions
7. https://proof.imagineqira.com/guides/github-actions-dependency-pinning
8. https://proof.imagineqira.com/guides/ssh-host-key-verification
9. https://proof.imagineqira.com/guides/release-gate-failure-modes

The technical guide pages are original engineering explanations with examples, limits of inference, primary GitHub documentation links, internal navigation and a reference to the verified pinned LOLM case. We did not create thin, duplicated, bulk-generated keyword variations.

## Site architecture and internal linking

The homepage now includes an editorial **Security field notes / methodology** section, links to the guide hub, two flagship guides, the case study and the illustrative report. All pages retain links back to the commercial offer and distinguish human review from the draft research scanner.

**ImagineQira parent-site crosslinks:** The main domain previously lacked any direct anchor to the new Qira Proof subdomain. Its \`imagineqira-site-proxy\` Worker was updated with a narrowly scoped, server-rendered contextual link in the footer of **\`/\` and \`/readiness/\` only**, linking to both https://proof.imagineqira.com/ and https://proof.imagineqira.com/case-study. The existing \`/pilots\` injection and all other routes remain unchanged.

- Parent Worker deployed version \`fc8d4a39-2d0a-4a0d-acf1-546f361d81f8\`, 100%.
- Original rollback version \`877cb99e-7e2a-4893-8655-2e15433fbc8a\`.
- The staging script's diff against original production was verified to be **one exact footer HTMLRewriter insertion**; we checked byte-for-byte reconstruction after removing that insertion before promoting it.
- Browser Rendering verified direct links on actual parent homepage and readiness page, original titles and H1s preserved, and \`/pilots\` explicitly unchanged.
- Both Cloudflare staging workers.dev subdomains were disabled after rollout to avoid public duplicate copies.

## Tests and live checks

- [GitHub CI: 276 JavaScript + 19 Python tests passed](https://github.com/TheArtOfSound/lolm/actions/runs/43860596314).
- 11 dedicated SEO tests check all 9 distinct pages, canonical URLs, descriptions, meta-robots, JSON-LD schema, sitemap URLs and lastmod, robots rules, 404/308/HEAD, IndexNow file, internal links, and the unmodified Stripe checkout and paid-intake privacy.
- Staging browser readbacks verified homepage, methodology, guide hub, a permissions guide, pinned case study, sitemap, robots file and noindex intake. Visual screenshot checks covered desktop guide hub and methodology plus mobile guide layout.
- Production browser readbacks verified the same paths, live public IndexNow file, and \`/health\` showing \`checkout_configured: true\`.
- Live Trend Stripe Payment Link \`plink_1UcLsTGz3eX0vCtEVB7vSsQI\` remains active at $299, with automatic tax enabled and redirect to \`/start-review\`. No charge was made.
- The D1 order ledger, daily \`17 3 * * *\` UTC (03:17) 180-day retention schedule and disabled webhook boundary were not changed. The webhook remains without signing secret, and \`/api/orders/health\` correctly reports \`unconfigured\`.

## Indexing status — explicit unknowns

**These pages are technically indexable; actual Google or Bing indexing has NOT been confirmed.** Search Console URL Inspection, indexed-page counts, sitemap acceptance, first crawl timestamps and performance metrics were not available.

- The connected GSC Wizard plugin returned \`payment_required\` because its trial/subscription is inactive. It cannot inspect or submit until that service is reactivated.
- Windsor.ai had no connected Search Console account for this property.
- Public sitemap and robots directives are live, but this alone is not equivalent to a Search Console Sitemaps submission.
- An IndexNow key is hosted and ready for validation. **No successful IndexNow notification response was obtained**; do not imply the URLs have been submitted or accepted.
- The available general web-fetch and container network environment could not independently access the domain, while actual Cloudflare Browser Rendering loaded the public routes successfully. This does not establish a Googlebot block; check Search Console's live URL test after access becomes available.

Google's published guidance states that a sitemap is a hint and indexing is not guaranteed. The URL Inspection tool is the relevant confirmation source; Bing recommends IndexNow for its participating search engines.

## Next operational steps

1. In Google Search Console, select/verify a domain property for \`imagineqira.com\` or a URL-prefix property for \`https://proof.imagineqira.com/\`. Submit \`https://proof.imagineqira.com/sitemap.xml\` and inspect the home, case study and four guides via **URL Inspection / Test Live URL**.
2. Use Bing Webmaster Tools to add the host and submit the same sitemap or perform an IndexNow request with the published ownership file; record the API response before reporting success.
3. Capture baseline **indexed pages, impressions, clicks, queries, and search appearance** before changing more metadata. Monitor for at least 2–4 weeks; distinguish discovery from traffic and conversions.
4. Check Cloudflare request/security logs for genuine Googlebot/Bingbot activity and unintended challenges, where available. Do not relax sitewide bot controls without evidence.
5. Validate actual user content usefulness, link discovery, and real buyer conversion; do not inflate content count with repetitive autogenerated pages.
6. Complete the separate payment verification and tax-registration work before calling the entire paid fulfillment journey fully automated.

The research scanner PR #71 remains draft. This SEO release does not certify that scanner or imply paid report fulfillment was completed.
