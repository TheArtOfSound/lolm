# Track 2B autonomous validation status

Last updated: 2026-08-02

## Current phase

30-task real-model qualification **complete** on SHA-pinned staging. Full qualification gate **not met** (24/30 competence). ≥150 **not started**. Production release **blocked**. Adaptive routing **OFF**.

## Frozen campaign identity

| Field | Value |
|-------|-------|
| Server SHA | `f15e5804b85134edb0b1e91f214627ce1998da54` |
| Deployment ID | `track2b-staging-f15e5804b851-20260802T065526Z` |
| Model | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` |
| Provider | `workers_ai` (approved production gateway) |
| Isolation | bwrap |
| Adaptive routing | OFF |
| Receipt kid | `track2b-staging-2026-08-743d37513368` |
| Public path | `https://lolm.imagineqira.com/api/track2b/*` |
| Runner harness SHA | `786b82b` (validation tooling only) |

## 30-task results (authoritative)

| Metric | Value |
|--------|-------|
| Total | 30 |
| Admitted | 30 |
| Trust passed | **30** |
| Competence passed | **24** |
| Qualification passed | **false** (gate = 30/30) |
| Aborted | false |
| Track 2B status | **unproven** |
| Adaptive routing applied | never |

Evidence:

- `/tmp/track2b-evidence/repo-gauntlet-live-a-30-workers.json`
- `/tmp/track2b-evidence/campaign_summary_30.json`
- `/tmp/track2b-evidence/live-a-30-workers.log`
- `/tmp/track2b-evidence/EVIDENCE_INDEX.json`

## Trust-zero (this campaign)

- Blind/stale mutations applied: 0 (no trust aborts)
- Receipt signature path: public-key verify on runner (PyNaCl)
- Secret leaks: 0
- Inadmissible integrity fails: 0 on final full run

## Prior invalidated campaigns (not competence claims)

1. SHA `743d375` — 0/30 competence — broken model path ("No model loaded")
2. Partial abort before L10 empty-SSE flake — preserved separately

## Root-cause fixes that enabled real competence

1. Missing `anthropic` SDK + invalid Anthropic key → switched to working **Workers AI** fixed model
2. Silent fallthrough to unloaded local model → strict Track 2B chat
3. Runner missing PyNaCl → runner venv + preflight check
4. Empty SSE flake → retries + longer first-byte wait

## Blockers

| ID | Detail | Continue when |
|----|--------|---------------|
| competence_below_30_30 | 24/30 admissible_pass | Stronger fixed model and/or task-family fixes; re-run full 30 from task 1 on same or new freeze SHA |
| anthropic_api_key_invalid | staging ANTHROPIC key 401 | Supply valid `ANTHROPIC_API_KEY` for Claude pin if desired |
| production_release | blocked until Track 1 + remote 2B gates | objective gates only |

## Next automated actions

1. Do **not** start ≥150 (qualification_passed=false).
2. Keep adaptive routing OFF.
3. Preserve evidence; optional stronger-model re-qualification when credentials allow.
4. Track 1 real-traffic factuality + passive Track 3 continue collecting on staging/prod as available.
5. No production canary until all release gates pass.

## Safety

- Adaptive routing: **OFF**
- Production release: **blocked**
- Private signing keys: server only
- Runner: public verify keys only
