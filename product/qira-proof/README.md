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

## Customer-path verification (November 15, 2026)

The isolated pilot now offers a complete client-side export path:

1. Connect the read-only GitHub App, or import an authorized local evidence snapshot.
2. Select the installed GitHub account, repository and workflow, if connected.
3. Review conditional findings and source links.
4. Under **Evidence**, select **Download printable report** to save a standalone HTML report.
   Open the downloaded file and choose Print → Save as PDF in the browser.
5. Separately download **evidence JSON** to preserve the deterministic SHA-256
   integrity receipt; the hash is neither a provider signature nor proof of remediation.
6. Disconnect the local browser session. If full GitHub authorization revocation is
   needed, revoke the App separately in GitHub.

### What is tested

- Real hosted preview renders its UI and serves /report.mjs.
- An integrated test executes the **compiled Worker** through an OAuth consent callback,
  installation listing, repository selection, workflow inspection, report generation,
  integrity verification and local disconnect, using simulated GitHub API responses.
- The downloadable report is generated from the same verified evidence receipt as the JSON.
- Report output escapes hostile source identifiers and uses restrictive static-document CSP.
- CI includes Node privacy, product UI and provider tests and Python collectors.

### What is not yet proven

- No real user-to-server GitHub OAuth callback has been completed by an external
  user during this validation. The real GitHub authorization interaction remains a
  human-controlled gate.
- No independent assessment has established accuracy at scale, exploitability or
  a customer security certification.
- GitHub local disconnect is not a provider-side token or App grant revocation.
- Cloudflare and Vercel are local collection options, **not** hosted OAuth connectors.
- No paid transaction, company billing integration or verified purchase was tested.

Keep the PR in draft status until live authorization, session/revocation review and
at least one independently reviewed, owner-authorized assessment succeed.

## Provider coverage and real connection status (November 15, 2026)

| Provider | Live customer OAuth | Local metadata collection | Review capability |
|---|---|---|---|
| GitHub | Isolated pilot, requires real owner authorization test | Yes, read-only selected workflow | SSH trust / unknown branch protection |
| Cloudflare | Not yet: application registration and scoped consent required | Yes, read-only selected Worker | Preview URL + privileged binding review |
| Vercel | Not yet: application registration and scoped consent required | **New:** read-only selected project and deployments | Preview protection review / latest production deployment error |

Do not market local token-based collection as one-click OAuth, claim live
cross-provider account linking, or promise full account security coverage.
Only the GitHub App pilot submits selected configuration *metadata*
transiently through the Qira Worker. **All local collector tokens remain in
the operator's own environment**; the resulting JSON is imported, combined,
analyzed and exported in the browser.

### Fast start for Vercel

First clone this repository or download `product/qira-proof/collector.py`
in a location where you can run Python 3.10+. Configure a Vercel access token
with only the read privileges needed for the project in your local terminal
environment. For team projects, specify the proper team ID:

~~~powershell
$env:VERCEL_TOKEN = "SET_LOCALLY_WITHOUT_SHARING"
$env:VERCEL_TEAM_ID = "team_YOUR_TEAM_ID"
python product/qira-proof/collector.py --vercel-project "YOUR_PROJECT" --out .\qira-vercel.json
~~~

The collector calls only Vercel's GET project/deployment metadata endpoints.
It reads project-level Vercel Authentication, password and trusted-IP
`enabled` flags, and bounded recent preview/production deployment states.
It never requests environment variable values, source files, logs,
deployments' sensitive metadata, or secret values. It emits only three
boolean-or-unknown facts per project, with no token or team identifier in
the local snapshot.

The available checks **do not** establish that preview URLs are reachable,
that all relevant protections are represented by those flags, or that a
failed deployment caused downtime.

### Combine provider evidence

Generate all three providers in one read-only command by setting the
appropriate local environment variables first:

~~~powershell
python product/qira-proof/collector.py --github-workflow "OWNER/REPO:.github/workflows/deploy.yml" --cloudflare-worker "YOUR_WORKER" --vercel-project "YOUR_PROJECT" --out .\qira-combined.json
~~~

Alternatively, start with one snapshot and choose
**Add another provider's evidence to this review** inside the local-file
section of the Qira app. This is browser-only and requires snapshots
collected within 24 hours, with no duplicated provider/asset/signal facts.
It does not link unrelated assets automatically: an asset's relationship
across clouds requires additional trusted mapping evidence, not a name guess.
The UI offers provider-specific commands and never accepts provider tokens.

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

The Worker serves static HTML/JavaScript and a narrowly scoped GitHub App OAuth pilot. It permits authenticated, CSRF-protected GitHub metadata POST selectors, but no arbitrary uploads or provider-token intake. There is no customer SaaS billing, subscription, or application database. GitHub live owner-authorization success has not been established.

## Commercial readiness gates

Before general customer onboarding: independent security review, access-controlled authentication if persistence is introduced, verified evidence provenance and signed attestations, least-privilege OAuth integrations, expanded rules with low false positives, design partners, measured time-to-value, explicit contracts, billing and support.

## Brand architecture

LOLM (https://lolm.imagineqira.com/) is a separate local AI agent and research architecture. QIRA Proof is an experimental assurance product, not a replacement for the existing LOLM website or CLI. A trained LOLM checkpoint has NOT been integrated with this product yet.
