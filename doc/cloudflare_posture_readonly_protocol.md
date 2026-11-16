# Event Horizon — Read-Only Cloudflare Evidence Protocol

This protocol is for **owner-authorized** infrastructure only. It does not
confer permission to collect another organization's traffic or configuration.

## Why this exists

The public Event Horizon Worker demonstrates fictional intervention models.
A separate offline tool now tests **observed Cloudflare configuration state**
without exposing actual configurations through the public research Worker.

A setting can be reported as observed. A failed or missing API read must
remain unknown or scoped absence, not a proven protection failure. A
configured setting alone is NOT evidence that a particular attack was stopped.

## Collection discipline

1. Verify that the account/zone is authorized and restrict calls to GET.
2. Do not export IPs, account IDs, zone IDs, access tokens, customer event
   logs, binding values, secret contents, or authorization headers.
3. Use a non-identifying zone alias and an explicit UTC observation time.
4. Map read failures honestly: a documented phase 404 may be recorded as
   no_entrypoint **for that scope and phase only**; unauthorized reads are
   permission_denied, not absence.
5. Store actual evidence outside public Git repositories and public Workers.
6. Keep a private authenticated service, per-tenant authorization and a
   retention policy as prerequisites for future customer evidence.

## Read-only Cloudflare API inspection

- Zone settings: GET /zones/{zone_id}/settings
- Zone ruleset phase: GET /zones/{zone_id}/rulesets/phases/{phase}/entrypoint
- Account ruleset phase: GET /accounts/{account_id}/rulesets/phases/{phase}/entrypoint
- Worker settings: GET /accounts/{account_id}/workers/scripts/{script_name}/settings
- Public Worker exposure: GET /accounts/{account_id}/workers/scripts/{script_name}/subdomain
- Worker domains: GET /accounts/{account_id}/workers/domains
- Account Access applications: GET /accounts/{account_id}/access/apps

Only inspect these three Ruleset phases for the current inventory:
http_request_firewall_managed, http_request_firewall_custom, http_ratelimit.
A cataloged managed ruleset is not necessarily executed. Legacy WAF
zone flags cannot establish effective modern Rulesets API coverage.
Cloudflare default DDoS protections are independent of these checks.

## Files

- qira_event_horizon/cloudflare_posture.schema.json
- qira_event_horizon/cloudflare_posture.example.json (fictional only)
- qira_event_horizon/cloudflare_posture.mjs (pure audit + diff)
- qira_event_horizon/cloudflare_posture_cli.mjs (offline Node CLI)
- qira_event_horizon/cloudflare_posture.test.mjs
- qira_event_horizon/cloudflare_posture_cli.test.mjs

## Reproduce offline

Requires Node.js 22+; no npm packages or network required.

~~~bash
node --check qira_event_horizon/cloudflare_posture.mjs
node --test qira_event_horizon/cloudflare_posture*.test.mjs

node qira_event_horizon/cloudflare_posture_cli.mjs \
  --current /secure/sanitized-observation.json

node qira_event_horizon/cloudflare_posture_cli.mjs \
  --previous /secure/earlier-observation.json \
  --current /secure/later-observation.json
~~~

The CLI prints JSON only. It performs no network requests or Cloudflare
mutations, accepts only allowlisted fields, refuses extra metadata,
limits the input to 128 KB and compares chronological same-scope snapshots.

The output SHA-256 binds only the operator-supplied sanitized input;
it is **not a Cloudflare-signed attestation**.

## Finding interpretation

- TLS minimum below 1.2: review compatibility with clients and other
  proxied hostnames before changing zone-wide settings.
- Full rather than Full (strict): validate ALL origin TLS certificate
  chains/hostnames and fallback paths before migrating.
- Rulesets not found: evidence of no entrypoint in inspected phase/scope,
  **not proof of no Cloudflare protection**.
- Public synthetic demo without Access: can be intentional, provided no
  customer data or sensitive bindings exist.
- Public demo with any bindings: review. Unknown bindings: unknown status.
- Private customer environment without Access: action required. Even
  with Access present, independently verify authorization and tenant isolation.

## Safe change-control gate

A policy change needs an accountable owner, observed baseline, identified
affected hosts/clients, an explicit hypothesis, a safe trial, legitimate
traffic disruption measurements, rollback readiness and post-change
verification. These steps are NOT executed by this tool.

## Research limitation

A before/after change is a descriptive observation, not causal
identification. Concurrent security rules, altered traffic volume,
instrumentation changes and regression to the mean can confound results.
Use controlled validation where practical; do not turn a config drift
diff into a quantified prevented-loss claim.

The next evidence milestone is opt-in authorized post-change observation,
not another simulated risk leaderboard.
