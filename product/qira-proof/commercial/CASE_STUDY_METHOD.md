# Qira Proof real-source case study: LOLM daily release workflow

**Live:** https://proof.imagineqira.com/case-study  
**Repository:** https://github.com/TheArtOfSound/lolm  
**Pinned commit:** \`f9700d2e661640da4a8d0cf2bb9c046d77f8a06b\`  
**Review type:** First-party static source cross-check; **not** an external independent audit.  
**Coverage:** One YAML workflow and its associated Python release-control script. The case study does not claim to review every workflow in the repo or the production runtime.

## Immutable source material

| Source | Git blob SHA-1 | Reproducible local fixture |
|---|---|---|
| \`.github/workflows/daily-lolm-learned-update.yml\` | \`631de3d0fe3ae22bfdf6881a15349a85ef6629ed\` | \`tests/fixtures/lolm_public_daily_workflow_f970.yml\` |
| \`scripts/agent_daily_update.py\` | \`07f2905691928cce87ba7a751b7889e6813cd7c8\` | \`tests/fixtures/lolm_public_daily_release_f970.py\` |

Both fixture byte streams were retrieved directly from public GitHub at the pinned commit. CI recalculates their Git blob object hashes, with the canonical Git object convention \`SHA1("blob " + byte_length + NUL + raw_content)\`, before trusting any source excerpt. The fixture contents are a snapshot of the public repository, not a secret or an assessed customer submission.

## What Qira Proof's scanner observed

Qira Proof's bounded YAML pattern scanner, running on the pinned 103-line workflow file, reported:

- \`workflow_token_write_permission.value=true\`, scopes \`contents\` line 19, \`pull-requests\` line 20, \`issues\` line 21, \`id-token\` line 22.
- \`workflow_unpinned_actions.value=true\` at line 32, including \`actions/checkout@v7\`, \`actions/setup-python@v7\` and \`actions/setup-node@v7\`.
- \`runtime_ssh_keyscan.value=true\` at line 62; the command appears in a conditional deploy-key step with \`|| true\`.

CI tests compare those scanner outputs to manually written exact-line assertions against the pinned fixtures. They verify the presence of source text, not the severity or exploitability of any observation. These checks are a first-party corroboration method, not independently adjudicated false-positive rates.

## What required separate manual source reading

These two observations **are not workflow-scanner detections**:

- \`scripts/agent_daily_update.py\` lines 147–162: a parsing error maps to \`high=0\` for \`npm audit\` output and can produce a passing security gate. No unsafe real release was demonstrated.
- \`scripts/agent_daily_update.py\` lines 172–184 and 277–316: \`gh pr merge --squash --admin\` is requested and later publishing/deploy paths do not enforce successful \`merged.ok\`. Actual release still depends on other gates and credentials. No bypass in production was demonstrated.

This manual control-flow review was previously documented in public [issue #72](https://github.com/TheArtOfSound/lolm/issues/72). The new case study makes the workflow-versus-manual distinction explicit.

## Publication, reliability and limitations

- Published in \`commercial/real_case.mjs\`, added to \`commercial/landing.mjs\` under \`/case-study\`, linked from the homepage and footer.
- Six immutable file/line hyperlinks support five observations. Every observation presents its source, interpretation, action and **what was not established**.
- CI [265 JavaScript / 19 Python tests passed](https://github.com/TheArtOfSound/lolm/actions/runs/43855709443). New tests check the source blob digests, exact line ranges, scanner output, manual orchestration conditions, claims/limitations and unchanged purchase flow.
- A separate Worker preview was rendered at desktop and mobile widths, with screenshots of the case-study header, findings, manual-review appendix and homepage feature. The final release was promoted to \`qira-proof-commercial\` Worker version \`c41ae02f-64d7-469e-be86-f7ebd08362a6\` (100% traffic).
- Production browser checks verified exactly **five finding rows and six pinned source links**, plus intact homepage checkout CTA and existing sample/intake routes.
- The live Trend $299 Stripe link, automatic tax, D1 and 180-day retention schedule remain unchanged. Stripe webhook remains disabled until a protected \`QIRA_STRIPE_WEBHOOK_SECRET\` is installed. No real payment was submitted, and no completed customer report is represented by this case study.

**Remaining research gate:** A reviewer unaffiliated with the development or authored fixtures must adjudicate a broader blinded real-world corpus, including ambiguous and unsupported YAML, before claims of independently validated scanner accuracy are justified.

## Ethical publication

This example uses the user's own publicly accessible LOLM repository and already-public issue #72. It does not reproduce secrets, access tokens, private source, runtime credentials, customer data or exploit instructions. Findings are deliberately scoped to a historical commit and must not be presented as current vulnerability status.
