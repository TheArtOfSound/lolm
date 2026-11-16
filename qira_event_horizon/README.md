# Qira Event Horizon

**Current product status:** public synthetic research demonstration, not an enterprise security product.

**Live URL:** https://horizon.imagineqira.com/  
**Cloudflare Worker:** `qira-event-horizon-research`  
**Public MCP endpoint:** `https://horizon.imagineqira.com/mcp` (stateless, experimental)
**OpenAPI contract:** https://horizon.imagineqira.com/openapi.json
**Shareable study example:** https://horizon.imagineqira.com/?case=credential-cascade&policy=31  
**Source:** `qira_event_horizon/` inside the LOLM repository  
**Development branch:** `research/artex-defense-lab-2026-11-15`; draft PR #59

## Purpose

Event Horizon is a verification-first security decision lab. Instead of
scoring an attack in isolation, it asks:

1. Which controls stop the **modeled** loss?
2. Which controls also interrupt legitimate business?
3. What happens when the simulator's assumptions prove wrong?
4. Can the result be reproduced and independently checked?
5. What **cannot** be concluded from the evidence?

### Current simulation

- 9 fictional scenarios: 5 malicious, 4 benign
- 5 optional controls; 32 enumerated combinations
- Deterministic state machine with explicit synthetic harm/effort units
- Pareto frontier over loss, legitimate friction and control complexity
- 6 assumption worlds across 32 policies
- Exact minimax-regret over declared worlds with stated utility convention
- SHA-256 integrity receipt covering returned result; **not a signature or model attestation**
- Read-only public API and narrow MCP JSON-RPC adapter
- Reproducible query links that preserve scenario ID and 0–31 policy bitmask

**Intentional counterexample:** An approved insider export survives all
modeled controls. No user should infer real detection accuracy or promised
prevention from these illustrations.

### Local test commands

Requires Node.js 22+; no npm packages.

```bash
node --check qira_event_horizon/engine.mjs
node --check qira_event_horizon/worker.mjs
node --check qira_event_horizon/robustness.mjs
node --check qira_event_horizon/mcp.mjs
node --test qira_event_horizon/*.test.mjs
```

GitHub Actions workflow: `.github/workflows/event-horizon-worker.yml`.

### Public API

`GET /health`: read-only deployment status.

`GET /api/meta`: fixed scenario and policy manifest.

`GET /openapi.json`: constrained machine-readable OpenAPI 3.1 contract.

`POST /api/evaluate` (JSON body): `{"scenarioId":"credential-cascade","policy":{"mfa":true}}`.

Returned content includes:
- selected scenario and trace
- harm/friction and baseline differences
- nondominated portfolios
- six assumption stress worlds and exact minimax-regret portfolio
- SHA-256 digest of the result JSON (excluding the receipt field)

This endpoint only accepts fixed scenario IDs and known boolean control keys.
It cannot accept arbitrary URLs, domains, targets, commands or scripts. It
stores no caller-provided records.

### MCP integration (experimental subset)

Stateless `POST /mcp` provides:

- `horizon.evaluate_policy`
- `horizon.control_frontier`
- `horizon.stress_assumptions`

Methods: `initialize`, `ping`, `tools/list`, `tools/call`, and
`notifications/initialized`. Supports basic 2026-07-28 Streamable HTTP
JSON responses plus legacy 2025 stateless tools requests. This is a narrow
implementation rather than complete MCP SDK conformance.

Example read-only call (2026-07-28):

```bash
curl -sS 'https://horizon.imagineqira.com/mcp' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' \
  -H 'Mcp-Name: horizon.evaluate_policy' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"horizon.evaluate_policy","arguments":{"scenarioId":"credential-cascade","policy":{"mfa":true}}}}'
```

**MCP tools are not installed automatically into any client.**
Connecting requires the client's own explicit configuration.

### Deployment

Cloudflare Worker uses three+ ESM modules:
`worker.mjs` (entrypoint), `engine.mjs`, `robustness.mjs`, and
`mcp.mjs`. Use multipart upload metadata with `main_module=worker.mjs`
and a supported Workers compatibility date. The custom domain is attached to
the isolated Worker script and does not modify the Qira website's existing
origin or routes.

### Privacy and security boundaries

- No real logs or customer identifiers
- No database, persistence, or outbound customer integration
- No credential or remote-target input
- Fail-closed input schema, bounded JSON request size, no CORS wildcard
- Content Security Policy on UI
- Named read-only MCP tools and validated request headers
- Public free research demo only; *do not* use for sensitive records
- Integrity hashing proves byte consistency, **not** who produced the data

Production requires independent safeguards:
Cloudflare Access/service tokens, tenant isolation, source-rights controls,
read-only least-privilege integrations, D1/R2 data separation, authorization
audits, opt-in retention policies, accountable receipts, rate limits and
third-party security review before any real customer data ingestion.

## Claims

Not supported: autonomous attack prevention, real LOLM checkpoint inference,
production cybersecurity efficacy, causal identification from observational
logs, validated financial savings, uniqueness, or market demand.

See `doc/event_horizon_commercial_thesis.md` for a pilot and commercialization plan.

## Phase 4 research: observed configuration without public ingestion

A separate **offline** Cloudflare configuration posture module now exists:
- cloudflare_posture.mjs: schema-strict control findings and drift analysis
- cloudflare_posture_cli.mjs: bounded, no-network CLI
- cloudflare_posture.schema.json: published JSON Schema 2020-12
- cloudflare_posture.example.json: fictional-only example
- doc/cloudflare_posture_readonly_protocol.md: collection, provenance,
  authorization and no-disruption runbook

This code does NOT query Cloudflare and is not deployed to the public Worker.
An operator provides a sanitized, explicitly allowlisted observation JSON.
The auditor reports observed edge TLS, SSL certificate-verification mode,
HTTPS redirect, managed/custom/rate-limit ruleset entrypoint presence, and
public vs private Access context. It will *not* declare a real attack blocked,
infer unknown statuses as off, or attest who created the snapshot.

~~~bash
node qira_event_horizon/cloudflare_posture_cli.mjs --current \
  qira_event_horizon/cloudflare_posture.example.json
node --test qira_event_horizon/cloudflare_posture*.test.mjs
~~~

Do not commit actual Cloudflare customer/account evidence into this public
repository or upload it to the public synthetic demo. This is an independent
observation research gate only, and no production settings are mutated.
