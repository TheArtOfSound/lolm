# Track 2B autonomous validation status

Last updated: 2026-08-02 (operator continuation)

## Current phase

30-task real-model qualification (Workers AI fixed model) — restarting after transient empty-SSE abort at L10.

## Frozen campaign identity

| Field | Value |
|-------|-------|
| Server SHA | `f15e5804b85134edb0b1e91f214627ce1998da54` |
| Deployment ID | `track2b-staging-f15e5804b851-20260802T065526Z` |
| Model | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` |
| Provider | `workers_ai` |
| Isolation | bwrap |
| Adaptive routing | OFF |
| Receipt kid | `track2b-staging-2026-08-743d37513368` |
| Public base | `https://lolm.imagineqira.com/api/track2b/*` |

## Partial evidence (aborted run, preserved)

`/tmp/track2b-evidence/repo-gauntlet-live-a-30-workers.json` (10 tasks):

- L01–L06, L08: **admissible_pass** (trust+competence)
- L07, L09: **agent_failure** (trust pass; wrong file edited)
- L10: **not_admitted** empty SSE (infrastructure flake; L10 retry alone admitted as agent_failure)

## Prior invalidated campaign

SHA `743d375` — 0/30 competence — model path broken (missing anthropic + invalid Anthropic key → "No model loaded"). Not competence evidence.

## Fixes landed

- Strict chat on staging (no silent local fallthrough)
- Staging rate floor / deploy Workers AI pin
- Runner PyNaCl required (preflight check)
- SSE empty-stream retries + longer first-byte wait

## Gates

- Production release: **blocked**
- Adaptive routing: **OFF**
- ≥150: only if 30-task qualification_passed
