# LOLM customer CLI cross-agent benchmark

Run ID: `20260910T223359Z`
Generated: `2026-09-10T22:33:59.507146+00:00`
Commit: `013d2deabced1b753e49cf4906c229cf20caf518`
Working tree dirty at launch: `False`

## Score

| Agent | Backend/model | Passed | Pass rate | Median wall time |
|---|---|---:|---:|---:|
| lolm_gemini | Google gemini-3.1-flash-lite via user-owned key | 5/5 | 100.0% | 7.9s |

## Task receipts

| Task | Tier | lolm_gemini |
|---|---|---|
| iso_duration | impl | UNSCORED |
| semver | impl | PASS |
| lru | impl | PASS |
| jsonpath | impl | PASS |
| bank_ledger | impl | UNSCORED |
| graph_topo | impl | PASS |
| fix_multifile_stats | fix | UNSCORED |
| fix_state_machine | fix | UNSCORED |
| fix_cache_ttl | fix | PASS |
| refactor_extract | refactor | UNSCORED |
| cli_wordfreq | cli | UNSCORED |
| pkg_calc | package | UNSCORED |

## Method

Each agent received the same task text and seed files in a fresh temporary directory. The hidden grader file did not exist until after the agent process exited. Grader exit code 0 is the only pass condition. Timeouts, raw stdout/stderr, grader output, artifact copies, and SHA-256 file hashes are retained beside this report.

LOLM rows measure the same customer CLI and tool runtime with the backend named in the score table. NFET status for this run is recorded in `results.json`; NFET is a trajectory controller and does not change the underlying model's raw knowledge. Codex uses the authenticated installed CLI and the model configured in the local Codex settings.

## Interpretation limits

This is a local product acceptance pilot, not an official SWE-bench or Terminal-Bench submission. A single trial per task has high variance and cannot establish broad superiority. Public frontier results must only be compared on their original harnesses. Runs blocked by authentication, quota, or provider infrastructure are marked UNSCORED rather than counted as model failures. Claude Code and Gemini CLI were not scored because no authenticated runnable Claude installation or Gemini credential was available during this run.

## Reproduce

```bash
python3 bench/validate.py
python3 bench/customer_cli/run_cross_agent.py --agents lolm_gemini --lolm-nfet
```
