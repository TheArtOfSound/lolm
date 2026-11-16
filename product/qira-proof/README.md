# QIRA Proof — Local-First Pilot

Preview: https://qira-proof-pilot-20261115.bryanleonard237.workers.dev/

Status: a read-only configuration assessment pilot, NOT a penetration test, breach finding, or commercial security certification. The sample shown by default is entirely fictional.

## Try the product in five minutes

1. Open the preview and inspect the fictional assessment.
2. Press "Sample recheck" to compare a later configuration snapshot.
3. Open "Evidence" and press "Export evidence report."
4. Use "Verify evidence file" to reproduce the analysis and detect alterations.

The browser application does not accept API credentials or upload data to its Worker. It runs the deterministic checks locally, with no server-side retention.

## Collect an authorized snapshot of your infrastructure

Requirements: Python 3.10+, a GitHub fine-grained token with metadata and contents READ for the selected repository, and a Cloudflare API token with Workers Scripts READ for the selected account.

Keep tokens in the local environment. Never paste them into the website, a GitHub issue, or a screenshot.

PowerShell setup:

    $env:GITHUB_TOKEN = "YOUR_READ_ONLY_GITHUB_TOKEN"
    $env:CLOUDFLARE_API_TOKEN = "YOUR_READ_ONLY_CLOUDFLARE_TOKEN"
    $env:CLOUDFLARE_ACCOUNT_ID = "YOUR_CLOUDFLARE_ACCOUNT_ID"

    python product/qira-proof/collector.py --github-workflow "TheArtOfSound/lolm:.github/workflows/deploy-production.yml" --cloudflare-worker "lolm-edge" --out ".\qira-baseline.json"

For macOS/Linux, export the same three environment variables and run:

    python3 product/qira-proof/collector.py --github-workflow 'TheArtOfSound/lolm:.github/workflows/deploy-production.yml' --cloudflare-worker 'lolm-edge' --out ./qira-baseline.json

Replace the example names with resources you own or are authorized to review. The collector resolves the actual GitHub default branch and accepts an explicitly selected workflow. It makes GET requests only; it does not export source code, secret values, credentials, raw logs, or personal identities.

Then upload the local JSON file with "Load baseline evidence" in QIRA Proof. Following an approved configuration change, run the collector again with a NEW output filename. Upload that as a follow-up. The collector refuses to overwrite existing files and sets owner-only permissions on Unix.

## Review conditions, not proven exploitation

- Deployment SSH trust: a selected workflow contains runtime ssh-keyscan and an independent, trusted host-key pin is not established. The action needs review; exploitability is not proven.
- Worker preview surface: a Worker has preview URLs enabled and privileged binding types. This does NOT mean secrets are exposed or that attackers can access the Worker.
- Branch-protection coverage: when GitHub authorization is insufficient, report UNKNOWN, not disabled.
- Additional workflow permission rules require independently verified evidence, not guesses.

The product cannot claim a fix succeeded because a flag disappeared. A follow-up snapshot reports which indicators cleared, remain, are new, or were not rechecked.

## Implementation

- collector.py: permission-scoped metadata collector, private file output.
- core.mjs: schema validation, conditional policy rules, comparisons, SHA-256 evidence.
- app.mjs/index.html: accessible local-first product UI.
- build.mjs: reproducible standalone Cloudflare Worker.
- tests/: Node and Python regression checks.

The Worker serves static HTML/JavaScript through GET/HEAD only, with connect-src 'none' in CSP. No OAuth, paid billing, accounts, or persistence is present.

## Commercial readiness gates

Before general customer onboarding: independent security review, access-controlled authentication if persistence is introduced, verified evidence provenance and signed attestations, least-privilege OAuth integrations, expanded rules with low false positives, design partners, measured time-to-value, explicit contracts, billing and support.

## Brand architecture

LOLM (https://lolm.imagineqira.com/) is a separate local AI agent and research architecture. QIRA Proof is an experimental assurance product, not a replacement for the existing LOLM website or CLI. A trained LOLM checkpoint has NOT been integrated with this product yet.
