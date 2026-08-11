# Customer CLI cross-agent benchmark

This suite evaluates the actual terminal products rather than calling their
underlying model APIs. Every task runs in a fresh temporary directory. Seed
files are copied in first; the hidden grader is written only after the agent has
exited. A grader exit code of zero is the only pass condition.

The default six-task pilot balances new implementations and repairs across
parsing, state, multiple files, edge cases, and verification. It is intentionally
small enough for local qwen3:14b runs on consumer hardware. Use `--repeat 3` or
more before treating small score differences as stable.

Run:

```bash
python3 bench/validate.py
python3 bench/customer_cli/run_cross_agent.py --agents lolm,codex --lolm-nfet
```

Artifacts land in `bench/customer_cli/results/<UTC timestamp>/`:

- `results.json`: machine-readable settings, results, hashes, and summaries
- `REPORT.md`: human-readable scorecard and limitations
- `raw/`: exact agent and hidden-grader stdout/stderr
- `artifacts/`: the files each agent produced

This is a local acceptance benchmark, not an official Terminal-Bench or
SWE-bench submission. Never compare its percentages directly with those public
leaderboards.
