# Track 2B autonomous validation status

Last updated: automated run

## Current phase

Staging deployment + full preflight in progress.

## SHAs

| Item | Value |
|------|-------|
| PR #15 merge baseline | `f1bd33f920cb552f281c6d829633ee2ef7feda34` |
| Validation branch tip (pre-freeze) | see git |

## Branch

`veyre/track2b-remote-validation`

## Blockers

See `/tmp/track2b-evidence/blockers.json` when present.

## Campaigns

| Campaign | Status |
|----------|--------|
| Workspace preflight | pending update |
| Staging deploy | in progress |
| Full preflight | pending |
| 30-task real-model | blocked until preflight green |
| ≥150 | blocked |

## Safety

- Adaptive routing: **OFF**
- Production release: **blocked**
- Private signing keys: server only
- Runner: public verify keys only
