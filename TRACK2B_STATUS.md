# Track 2B autonomous validation status

Last updated: 2026-08-02 (operator continuation)

## Current phase

Fix real-model path (invalid Anthropic + missing SDK → switch to approved Groq fixed model), redeploy SHA-pinned staging, re-run preflight + 30-task qualification from task 1.

## Root cause of 0/30 competence (campaign SHA 743d375)

1. Staging venv lacked `anthropic` package → Claude path always failed.
2. Staging `ANTHROPIC_API_KEY` returns **401 invalid x-api-key**.
3. `_operator_chat` swallowed remote errors and fell through to unloaded local `generation_loop` → agent_failure `"No model loaded. Click Load model first."` with valid receipts.
4. Burst concurrency hit rate limit (L30 429).

## Fix in progress

- Install anthropic (for optional Claude path).
- Pin fixed real model to **Groq `llama-3.3-70b-versatile`** using existing approved `GROQ_API_KEY` from production demo env.
- Strict chat on Track 2B staging (no silent local fallthrough).
- Staging rate floor default 120/min when staging API key set.
- Deploy script syncs provider keys without printing secrets.

## SHAs

| Item | Value |
|------|-------|
| PR #15 merge baseline | `f1bd33f920cb552f281c6d829633ee2ef7feda34` |
| Prior campaign freeze (invalid model path) | `743d375133687b8ad68cda3f685bdc145412904c` |
| Validation branch tip | see git after push |

## Branch

`veyre/track2b-remote-validation`

## Campaigns

| Campaign | Status |
|----------|--------|
| Workspace preflight | PASS (clean clone) |
| Prior 30-task @ 743d375 | COMPLETE — competence **0/30** (model path broken; trust 29/29 admitted; L30 rate-limit) — **invalidated for competence claims** |
| Staging redeploy + full preflight | in progress |
| 30-task real-model (new SHA) | pending redeploy |
| ≥150 | blocked until 30-task qualification passes |

## Safety

- Adaptive routing: **OFF**
- Production release: **blocked**
- Private signing keys: server only
- Runner: public verify keys only
- No silent alteration of fixtures/scoring
