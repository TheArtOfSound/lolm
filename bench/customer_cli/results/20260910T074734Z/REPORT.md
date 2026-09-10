# LOLM customer CLI cross-agent benchmark

Run ID: `20260910T074734Z`
Generated: `2026-09-10T07:47:34.388933+00:00`
Commit: `2ce1dd4f75eb66e74dee975a3f472d1bf301a3b1`
Working tree dirty at launch: `True`

## Score

| Agent | Backend/model | Passed | Pass rate | Median wall time |
|---|---|---:|---:|---:|
| lolm_gemini | Google gemini-3.1-flash-lite via user-owned key | 11/12 | 91.7% | 81.3s |
| lolm_gemini_nonfet | Google gemini-3.1-flash-lite, NFET disabled (ablation) | 11/12 | 91.7% | 60.1s |

## Task receipts

| Task | Tier | lolm_gemini | lolm_gemini_nonfet |
|---|---|---|---|
| iso_duration | impl | PASS | PASS |
| semver | impl | PASS | PASS |
| lru | impl | PASS | PASS |
| jsonpath | impl | PASS | PASS |
| bank_ledger | impl | PASS | PASS |
| graph_topo | impl | PASS | PASS |
| fix_multifile_stats | fix | PASS | PASS |
| fix_state_machine | fix | PASS | PASS |
| fix_cache_ttl | fix | PASS | FAIL |
| refactor_extract | refactor | PASS | PASS |
| cli_wordfreq | cli | PASS | PASS |
| pkg_calc | package | FAIL | PASS |

## Method

Each agent received the same task text and seed files in a fresh temporary directory. The hidden grader file did not exist until after the agent process exited. Grader exit code 0 is the only pass condition. Timeouts, raw stdout/stderr, grader output, artifact copies, and SHA-256 file hashes are retained beside this report.

LOLM rows measure the same customer CLI and tool runtime with the backend named in the score table. NFET status for this run is recorded in `results.json`; NFET is a trajectory controller and does not change the underlying model's raw knowledge. Codex uses the authenticated installed CLI and the model configured in the local Codex settings.

## Interpretation limits

This is a local product acceptance pilot, not an official SWE-bench or Terminal-Bench submission. A single trial per task has high variance and cannot establish broad superiority. Public frontier results must only be compared on their original harnesses. Runs blocked by authentication, quota, or provider infrastructure are marked UNSCORED rather than counted as model failures. Claude Code and Gemini CLI were not scored because no authenticated runnable Claude installation or Gemini credential was available during this run.

## Reproduce

```bash
python3 bench/validate.py
python3 bench/customer_cli/run_cross_agent.py --agents lolm_gemini,lolm_gemini_nonfet --lolm-nfet
```
