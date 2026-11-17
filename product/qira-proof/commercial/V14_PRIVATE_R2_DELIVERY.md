# Qira Proof V14 — R2 private report fulfillment

**Production:** https://proof.imagineqira.com/  
**Customer access:** https://proof.imagineqira.com/report-access  
**R2 bucket:** `qira-proof-deliverables` (Standard, western North America hint, **private**)  
**R2 Worker binding:** `QIRA_PROOF_REPORTS` on `qira-proof-commercial`  
**Production D1:** `qira-proof-orders-20261116` / `8554f204-0b7b-4c15-8307-4786c8443cf3`  
**Worker version:** `8cc0a200-bbba-46e2-ac12-1f8e12485145` / 100% production traffic  
**Stripe merchant:** Trend; $299 existing one-time founding review

## What is actually running

- Cloudflare R2 bucket created and confirmed to have **no r2.dev public access** and **no custom public domain**. Public requests cannot list/upload/download raw objects.
- Live Worker has six bindings: `QIRA_PROOF_REPORTS` (R2), original D1, Trend checkout URL, and three original protected secrets (Stripe webhook, email HMAC pepper, and restricted Resend sender).
- Two additive D1 tables created: `qira_deliverables` (operator-approved file metadata, immutable object key, filename, SHA-256, byte length, release/revocation) and `qira_report_challenges` (10-minute access-code digest, throttling, failed attempts and single-use consumption).
- Two endpoints are active:
  - `POST /api/reports/request-code` requires exact same-origin JSON, full live Checkout Session ID and checkout email. It verifies a **paid, nonrefunded order**, that the source/intake is `delivered`, that a report was human-released and not revoked, and that the buyer email matches the signed Stripe checkout digest. It sends the eight-digit short-lived code **only to the checkout mailbox**. The public response is uniformly generic for missing reports, incorrect emails and unsuccessful lookups.
  - `POST /api/reports/download` requires the same order and mailbox, the correct eight-digit code, no earlier consumption, an unexpired 10-minute window, and fewer than five failed attempts. The Worker reads **only the exact approved object key** from its private R2 binding, checks the entire document byte count and SHA-256 and atomically consumes the code. Files are forced to download as `application/octet-stream`; HTML never renders inline. Tokens never appear in download query strings.
- Report size is limited to 10 MiB. Accepted approved file types are PDF, HTML and JSON. Object keys require the restricted shape `reports/<identifier>/file.pdf|html|json` and file names are sanitized before placing them in Content-Disposition.
- Same-origin browser forms and explicit status feedback are available at `/report-access`. Shared navigation includes the new retrieval route. Search indexing is disabled for the customer-access page.
- The existing daily cleanup `17 3 * * *` UTC now removes code records older than one day past expiry; the five-minute notification cron remains untouched.
- An isolated **stage-only** R2 bucket and D1 were used to load a synthetic PDF, insert a synthetic approved order/intake and test the rendering. R2 upload and authenticated management API retrieval returned the expected file. There were **no production synthetic orders/files**.
- Passing GitHub Actions run: [322 JavaScript tests, 19 Python tests](https://github.com/TheArtOfSound/lolm/actions/runs/43988364635). New tests cover a matching buyer, replay denial, wrong checkout email, unpaid orders, partial refunds, revoked files, altered bytes, expired/reused codes, lockout and cross-origin requests.
- After production deployment **26 browser checks passed** (13 public routes at 390 and 1280 pixels): correct primary heading, no horizontal overflow, one main landmark, no missing in-page hash targets, duplicate IDs or unlabeled inputs. Independent external assistive-technology testing remains pending.
- Production D1 had zero orders, intakes, released reports or access codes on latest read. No real customer document delivery has occurred, and actual production email-to-Worker OTP delivery for an authorized customer remains untested.

## Human-controlled report release — the exact operational flow

No anonymous or public upload endpoint exists. An authorized operator uploads via Cloudflare's protected Dashboard or account-scoped API, never by posting a file to the storefront. An upload **does not** release a file.

1. In **Trend Stripe**, verify the exact $299 `Checkout Session` and `PaymentIntent` are paid, not refunded or disputed, and match the stored order.
2. In restricted Cloudflare D1, inspect that the buyer submitted intake for that session. Confirm the checkout email, actual authorization to inspect the chosen GitHub repository and the agreed scope. The repository and work must already have been reviewed by a human; do not assume OAuth or a public repository proves permission.
3. Prepare the actual reviewed document, verify a bounded source scope, clear file references, accurate caveats and a human signoff. Store the final reviewed PDF (preferred), or HTML/JSON, at a unique immutable R2 object key such as `reports/cs_live_REDACTED/approved.pdf`, in private bucket `qira-proof-deliverables`. The actual object key must use only ASCII letters, numbers, underscores, dashes and slashes, with a single `.pdf`, `.html` or `.json` extension. **Never overwrite a previously released object**; create a new version key and reconcile previous customer notices.
4. Validate the uploaded object by rereading it from R2 through an authenticated Cloudflare interface and recomputing its full SHA-256 and byte length. Only trusted report files 1–10,485,760 bytes are eligible. Do not copy customer content into tickets, public PRs, or chat logs.
5. Authorize publication by entering exactly one D1 `qira_deliverables` row for the validated paid session. Verify `approved_at`, `released_at`, byte length, object key, digest, and review signoff **before** creating the record. Use a restricted D1 operator session, not a public HTTP endpoint. Template SQL (replace placeholders with real verified values):

```sql
INSERT INTO qira_deliverables
(session_id,object_key,file_name,media_type,sha256,byte_length,approved_at,released_at,revoked_at)
SELECT o.session_id,
       'reports/ACTUAL_SESSION/approved.pdf',
       'qira-proof-review.pdf',
       'application/pdf',
       'ACTUAL_64_CHARACTER_LOWERCASE_SHA256',
       ACTUAL_BYTE_LENGTH,
       strftime('%s','now'),
       strftime('%s','now'),
       NULL
FROM qira_orders o
JOIN qira_intakes i ON i.session_id=o.session_id
WHERE o.session_id='ACTUAL_VERIFIED_SESSION'
  AND o.status='paid' AND o.refund_amount=0
  AND i.state='in_review'
  AND NOT EXISTS(SELECT 1 FROM qira_deliverables d WHERE d.session_id=o.session_id);
```

6. After publishing and successfully sending the approved delivery notice to the verified checkout email, mark the associated intake `delivered`. This is the final eligibility gate that permits email-code issuance:

```sql
UPDATE qira_intakes
SET state='delivered'
WHERE session_id='ACTUAL_VERIFIED_SESSION'
  AND state='in_review'
  AND EXISTS (
    SELECT 1 FROM qira_deliverables d
    JOIN qira_orders o ON o.session_id=d.session_id
    WHERE d.session_id=qira_intakes.session_id
      AND d.revoked_at IS NULL AND o.status='paid' AND o.refund_amount=0
  );
```

7. Notify the customer via the existing verified contact channel: their report is ready at `https://proof.imagineqira.com/report-access`. They will enter the Stripe Checkout Session ID, checkout email, and one-time emailed code. **Do not send their report as a public R2 link, attach sensitive repo files in plaintext emails, or ask them to share passwords/tokens.**
8. If authorization is withdrawn, a report is wrong, or the service is disputed, immediately revoke the report record before any additional downloads:

```sql
UPDATE qira_deliverables
SET revoked_at=strftime('%s','now')
WHERE session_id='ACTUAL_VERIFIED_SESSION' AND revoked_at IS NULL;
```

This revokes new code issuance and subsequent file downloads. It cannot retract a file already downloaded. Keep Stripe authoritative and independently reconcile payment reversals even when a cached D1 `paid` status exists.

## Operational safety and abuse limits

- 10-minute short-lived **random eight-digit access code**; 1 successful use; 5 failed attempts; max 3 codes per order per hour and a 90-second interval between resends. Browser access codes travel in POST JSON bodies, not query strings.
- The code digest is computed with a distinct HMAC message domain under the existing Cloudflare protected `QIRA_ORDER_EMAIL_PEPPER` secret. Raw codes are not stored in D1 or report object metadata.
- No download unless the object exists, is within 10 MiB, and its SHA-256 and byte length match the human-approved D1 release entry.
- Always private/no-store HTTP responses, no anonymous R2 key browsing, no R2 CORS, no raw report access via R2 public domains, no Worker public upload path.
- If the email provider rejects a code notification, the code does not grant access by itself and the customer can retry after the throttle interval. The public response avoids exposing the customer's mailbox or whether an unreleased report exists. A genuine inbox-delivery test with a consenting recipient is still required.
- No payment, report or access code was invented in the production database. Do **not** set `i.state='delivered'` simply to test email delivery.
- There is no automatic report generation or unattended approval: repository consent, manual corroboration, professional scope and human signoff remain necessary before files are released.

## Read-only operator inspections

```sql
SELECT o.session_id, o.status, o.refund_amount, i.state,
       d.object_key, d.byte_length, d.sha256,
       datetime(d.released_at,'unixepoch') AS released_utc,
       datetime(d.revoked_at,'unixepoch') AS revoked_utc
FROM qira_orders o
LEFT JOIN qira_intakes i ON i.session_id=o.session_id
LEFT JOIN qira_deliverables d ON d.session_id=o.session_id
ORDER BY o.updated_at DESC LIMIT 50;
```

```sql
SELECT
 (SELECT COUNT(*) FROM qira_orders) AS orders,
 (SELECT COUNT(*) FROM qira_intakes) AS intakes,
 (SELECT COUNT(*) FROM qira_deliverables WHERE revoked_at IS NULL) AS published_reports,
 (SELECT COUNT(*) FROM qira_report_challenges WHERE expires_at >= strftime('%s','now') AND consumed_at IS NULL) AS active_codes;
```

## Deferred real-world acceptance gates

- Actual paid Stripe webhook → verified intake → consent-based GitHub workflow inspection → human-signed report → private R2 upload → approved publication → customer notice → one-time email code → actual retrieved bytes. The Node tests and R2 staging checks do not substitute for a real complete customer journey.
- Independently test recovery from Resend API outages, R2 timeouts, Stripe event ordering, manually edited D1 release records, and recipient accessibility with a real screen reader.
- Validate legal tax registrations and customer data-retention policy before expanding merchant scope. R2 objects are **not automatically purged** because deleting contractual deliverables is a business decision.

**Do not claim that a real customer received a report until the operator observes an actual completed, authorized customer delivery.**
