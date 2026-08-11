# LOLM customer CLI cross-agent benchmark

Run ID: `20260811T021336Z`
Generated: `2026-08-11T02:13:36.753060+00:00`
Commit: `ff1c42e109c2367920304d64471ec8be9bf48491`
Working tree dirty at launch: `True`

## Score

| Agent | Backend/model | Passed | Pass rate | Median wall time |
|---|---|---:|---:|---:|
| lolm_cerebras | Cerebras gpt-oss-120b via user-owned key | 6/6 | 100.0% | 131.1s |
| codex | gpt-5.6-sol, high reasoning (local config at launch) | 0/0 (6 excluded) | UNSCORED | 4.4s |

## Task receipts

| Task | Tier | lolm_cerebras | codex |
|---|---|---|---|
| iso_duration | impl | PASS | UNSCORED |
| semver | impl | PASS | UNSCORED |
| expr_eval | impl | PASS | UNSCORED |
| jsonpath | impl | PASS | UNSCORED |
| fix_multifile_stats | fix | PASS | UNSCORED |
| fix_state_machine | fix | PASS | UNSCORED |

## Method

Each agent received the same task text and seed files in a fresh temporary directory. The hidden grader file did not exist until after the agent process exited. Grader exit code 0 is the only pass condition. Timeouts, raw stdout/stderr, grader output, artifact copies, and SHA-256 file hashes are retained beside this report.

LOLM rows measure the same customer CLI and tool runtime with the backend named in the score table. NFET status for this run is recorded in `results.json`; NFET is a trajectory controller and does not change the underlying model's raw knowledge. Codex uses the authenticated installed CLI and the model configured in the local Codex settings.

## Interpretation limits

This is a local product acceptance pilot, not an official SWE-bench or Terminal-Bench submission. A single trial per task has high variance and cannot establish broad superiority. Public frontier results must only be compared on their original harnesses. Runs blocked by authentication, quota, or provider infrastructure are marked UNSCORED rather than counted as model failures. Claude Code and Gemini CLI were not scored because no authenticated runnable Claude installation or Gemini credential was available during this run.

## Reproduce

```bash
python3 bench/validate.py
python3 bench/customer_cli/run_cross_agent.py --agents lolm_cerebras,codex --lolm-nfet
```
