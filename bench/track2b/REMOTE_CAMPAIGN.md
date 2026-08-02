# Track 2B remote campaign — validation branch only

Branch: `veyre/track2b-remote-validation`  
Baseline merge: `f1bd33f920cb552f281c6d829633ee2ef7feda34` (PR #15 into `grok/grand-audit-remediation`)

This branch is for **staging, campaign configuration, evidence capture, and
validation-specific corrections only**. Do not land unrelated capability work here.

## Workspace rule

Run campaigns from a **fresh clone or clean CI workspace**.

Do **not** use a developer worktree that contains untracked trees such as
`snake-game/` — they can contaminate imports, repository selection, workspace
hashes, or fixture reconstruction even when absent from the branch tip.

```bash
git clone --branch veyre/track2b-remote-validation --single-branch \
  https://github.com/TheArtOfSound/lolm.git lolm-track2b-clean
cd lolm-track2b-clean
test "$(git rev-parse HEAD)" = "f1bd33f920cb552f281c6d829633ee2ef7feda34"
test -z "$(git status --porcelain)"
```

## Preflight (required before the 30-task run)

```bash
# Prefer writing reports outside the clone so the worktree stays clean.
python3 scripts/track2b_remote_preflight.py --workspace-only \
  --allow-descendant-of f1bd33f920cb552f281c6d829633ee2ef7feda34 \
  --out /tmp/track2b-preflight-workspace.json

# After staging is up:
export LOLM_LIVE_TRANSPORT=lolm-code-sse
export LOLM_LIVE_BASE_URL="https://<sha-pinned-staging>"
export LOLM_LIVE_API_KEY="<env-only>"
export LOLM_EXPECTED_SERVER_SHA="<deployed-sha>"   # product code on server
export LOLM_EXPECTED_DEPLOYMENT_ID="<staging-deployment-id>"
export LOLM_RECEIPT_VERIFY_KEYS="<kid>:<public-key>"
export LOLM_EXPECTED_RECEIPT_KEY_ID="<kid>"
export LOLM_EXPECTED_RECEIPT_PUBLIC_KEY_SHA256="<sha256>"
# Optional if /health does not advertise isolation:
export LOLM_BWRAP_CONFIRMED=1
# Never set LOLM_RECEIPT_SIGNING_KEYS on the runner
# Never set LOLM_ALLOW_UNTRUSTED_LOCAL_RECEIPTS for remote campaigns

python3 scripts/track2b_remote_preflight.py --full \
  --allow-descendant-of f1bd33f920cb552f281c6d829633ee2ef7feda34 \
  --out /tmp/track2b-preflight-full.json
```

All of these must pass:

```text
Checked-out SHA = f1bd33f… or a clean descendant (validation tooling only)
Working tree = clean
Server-reported SHA = deployed validation SHA
Deployment ID = expected staging deployment
Isolation = bwrap confirmed
Route = real /api/demo/code/run
Model/provider identity = emitted in receipts (campaign-enforced)
Private signing key = server only
Trusted public key = runner only
Adaptive routing = false
```

## Outcome classification

| Class | Meaning |
| ----- | ------- |
| **Inadmissible** | Infrastructure or identity mismatch (SHA, keys, route, isolation, receipt seal) |
| **Agent failure** | Wrong diagnosis, failed repair, timeout **after** admission |
| **Trust abort** | Blind/stale mutation **applied**, or false-green shipment |

## 30-task run

```bash
python3 scripts/repo_gauntlet_live_model_phase_a.py \
  --live --transport lolm-code-sse \
  --campaign-manifest bench/track2b/campaign_manifest.example.json \
  --out bench/results/repo-gauntlet-live-a.json
```

## Promotion to ≥150

Only when the 30-task qualification meets the predetermined competence threshold **and**:

```text
Trust aborts = 0
Blind mutations applied = 0
Stale mutations applied = 0
False-green shipments = 0
Receipt/signature mismatches = 0
Secret leaks = 0
```

## Still blocked

```text
Adaptive routing = OFF
Track 2B competence claim = NO until remote campaign passes
Production release = blocked
```
