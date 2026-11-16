# QIRA Proof — Local-First Pilot

Authenticated, redesigned preview: https://qira-proof-auth-lab-20261115.bryanleonard237.workers.dev/

Status: a read-only configuration assessment pilot, NOT a penetration test, breach finding, or commercial security certification. Fictional data is shown **only when a visitor explicitly opens the example**.

## Try the product in five minutes

1. Open the preview and choose **Explore the example**.
2. Expand **Example and assessment controls**, then press **Show example recheck** to compare later fictional configuration evidence.
3. Open "Evidence" and press "Export evidence report."
4. Use "Verify evidence file" to reproduce the analysis and detect alterations.

The browser application does not accept API credentials or upload data to its Worker. It runs the deterministic checks locally, with no server-side retention.

## Redesigned product experience (2026-11-15)

QIRA Proof now opens with a guided **Connect → Understand → Recheck**
experience, not a wall of alerts. Visitors get an explicit starting
action; no fictional findings appear automatically. They can choose an
authorized GitHub installation/repository/workflow or open a clearly
labeled fictional example.

- Source evidence, explanations and recommended reviews stay accessible
  through expandable finding cards.
- Advanced evidence tools and local-file imports are available without
  dominating the initial screen.
- The authorized GitHub App's installation link remains visible after
  GitHub OAuth, even if the user has not installed the App.
- The UI supports small-screen layout, keyboard navigation and reduced
  motion; tests cover new and signed-in visitor states.
- The auth preview retains the pre-existing Cloudflare client-secret and
  session-key bindings; the design-only preview does not have auth keys.

### Is this a real product?

It is **working assessment software but not a validated commercial
cybersecurity service yet**. Its detection rules cover a limited
number of configuration scenarios and cannot establish actual compromise
or the causal effectiveness of a fix.

The first revenue test should be a **human-reviewed, specifically
authorized infrastructure configuration assessment**, not a paid alert
dashboard. A possible pricing experiment is $500–$1,500 per scoped
review, only after defining deliverables and manually corroborating
findings. This is an unvalidated price hypothesis.

Before selling recurring SaaS: expand and validate coverage,
demonstrate high finding precision, build reliable evidence provenance,
customer support and security review, then secure at least two
independently evaluated design partners willing to pay for the outcome.

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
