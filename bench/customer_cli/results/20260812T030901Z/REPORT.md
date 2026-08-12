# LOLM customer CLI cross-agent benchmark

Run ID: `20260812T030901Z`
Generated: `2026-08-12T03:09:01.518587+00:00`
Commit: `3bae2fd7a82ae001f8531e9d9cd3d8a4305e1219`
Working tree dirty at launch: `False`

## Score

| Agent | Backend/model | Passed | Pass rate | Median wall time |
|---|---|---:|---:|---:|
| lolm_gemini | Google gemini-3.1-flash-lite via user-owned key | 23/25 | 92.0% | 103.7s |
| gemini | installed Gemini CLI on gemini-3.1-flash-lite via user-owned key | 18/18 | 100.0% | 59.3s |

## Task receipts

| Task | Tier | lolm_gemini | gemini |
|---|---|---|---|
| iso_duration | impl | PASS | PASS |
| roman | impl | PASS | PASS |
| interval_merge | impl | PASS | PASS |
| lru | impl | PASS | PASS |
| semver | impl | PASS | PASS |
| expr_eval | impl | PASS | PASS |
| jsonpath | impl | PASS | PASS |
| wrap | impl | PASS | PASS |
| fix_pagination | fix | PASS | PASS |
| fix_multifile_stats | fix | PASS | PASS |
| fix_state_machine | fix | PASS | PASS |
| fix_csv_parser | fix | PASS | PASS |
| fix_cache_ttl | fix | PASS | PASS |
| fix_argsplit | fix | PASS | PASS |
| fix_retry | fix | PASS | PASS |
| fix_date_range | fix | PASS | PASS |
| refactor_shapes | refactor | PASS | PASS |
| refactor_extract | refactor | PASS | PASS |
| tdd_matrix | tdd | PASS | UNSCORED |
| cli_wordfreq | cli | PASS | UNSCORED |
| cli_csvstat | cli | FAIL | UNSCORED |
| pkg_calc | package | PASS | UNSCORED |
| json_patch | impl | UNSCORED | UNSCORED |
| graph_topo | impl | PASS | UNSCORED |
| config_merge | impl | FAIL | UNSCORED |
| bank_ledger | impl | PASS | UNSCORED |

## Method

Each agent received the same task text and seed files in a fresh temporary directory. The hidden grader file did not exist until after the agent process exited. Grader exit code 0 is the only pass condition. Timeouts, raw stdout/stderr, grader output, artifact copies, and SHA-256 file hashes are retained beside this report.

LOLM rows measure the same customer CLI and tool runtime with the backend named in the score table. NFET status for this run is recorded in `results.json`; NFET is a trajectory controller and does not change the underlying model's raw knowledge. Codex uses the authenticated installed CLI and the model configured in the local Codex settings.

## Interpretation limits

This is a local product acceptance pilot, not an official SWE-bench or Terminal-Bench submission. A single trial per task has high variance and cannot establish broad superiority. Public frontier results must only be compared on their original harnesses. Runs blocked by authentication, quota, or provider infrastructure are marked UNSCORED rather than counted as model failures. Claude Code and Gemini CLI were not scored because no authenticated runnable Claude installation or Gemini credential was available during this run.

## Reproduce

```bash
python3 bench/validate.py
python3 bench/customer_cli/run_cross_agent.py --agents lolm_gemini,gemini --lolm-nfet
```
