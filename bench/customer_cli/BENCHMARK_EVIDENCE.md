# LOLM benchmark evidence — 2026-08-11

## Bottom line

LOLM with the user-owned Cerebras `gpt-oss-120b` backend passed all six tasks in
the customer-CLI acceptance pilot: **6/6 hidden graders (100%)**. Every pass was
produced in a fresh workspace and graded after the agent process ended.

This run does **not** prove that LOLM equals or beats Codex, ChatGPT, or Claude
Code broadly. The installed Codex CLI hit its ChatGPT usage limit before every
task, so all six Codex rows are correctly marked **UNSCORED**, not failures.
Claude Code was not installed and Gemini CLI had no configured credential. A
direct frontier parity claim therefore remains open.

## Exact result

| Track | Scoreable result | Median agent time | Status |
|---|---:|---:|---|
| LOLM 1.2 development tree + NFET + Cerebras `gpt-oss-120b` | 6/6 | 131.1s | Valid pilot |
| Codex CLI 0.147.0-alpha.6.5 + configured `gpt-5.6-sol` high | 0/0 | 4.4s to quota response | Unscored |

The six LOLM passes cover four new implementations and two seeded repairs:

- ISO-8601 duration parsing
- semantic-version precedence
- arithmetic parsing without `eval` or `exec`
- nested dotted/bracket path traversal
- a two-module statistics repair
- an order state-machine repair

The machine-readable result is
[`results.json`](results/20260811T021336Z/results.json), and the concise
scorecard is [`REPORT.md`](results/20260811T021336Z/REPORT.md). Raw agent output,
grader output, produced artifacts, timings, and SHA-256 hashes are retained
under the same run directory.

Result-file SHA-256 at report generation:

```text
b9fe68fee750875633192ceb19dab009152488d1618f8b87923b8a04f7f87223  results.json
68edf9637fddf7e58cbaa630a347affbc033828b5d4b800e4c7f227687a8dc91  REPORT.md
```

## Why the evidence is meaningful

The runner creates a new temporary directory for every agent/task pair, copies
only the seed files, and does not create the hidden grader until the agent has
exited. Grader exit code zero is the sole pass condition. The benchmark
validator separately proves that every reference solution passes and every
seeded repair starts broken.

The run also retains negative evidence. Two earlier launches are not treated as
scores because they exposed a dropped local Ollama stream, provider-rate-limit
handling, and an invalid Python isolation flag in the first grader version.
Those defects were fixed before the valid run.

Five of the six LOLM tasks ended with a complete product receipt containing
`verified:true`, real trained-head telemetry, `checkpoint:"result"`, and NFET
decision `finalize` from `verified_result`. The multi-file repair still passed
its hidden grader but reached the then-configured 10-step ceiling before a clean
final receipt. That finding led to three runtime improvements: provider tool
envelope normalization, an explicit `python3` rule on macOS, and restoration of
the normal 12-step autonomous budget. It is not rewritten as a cleaner result.

## What improved because of the benchmark

- Natural `lolm run "Create solution.py …"` tasks now route to the write-capable
  agent instead of read-only question mode.
- Local qwen receives a smaller task-specific tool schema and one bounded
  Ollama transport retry.
- OpenAI-compatible providers honor HTTP 429 `Retry-After` with bounded retries.
- Harmless provider-added `tool` envelope metadata no longer consumes a failed
  step against strict schemas.
- An empty `fs.list` path safely normalizes to the current trusted workspace.
- Python instructions prefer `python3` unless another executable is proven.
- Codex quota/auth failures are excluded as infrastructure failures rather than
  misrepresented as model losses.
- Raw receipts now parse LOLM verification, usage, NFET decision, and telemetry
  into the result JSON.

## Public benchmark boundary

This pilot follows the core evidence pattern used by serious agent evaluations,
but it is not interchangeable with their percentages. SWE-bench Verified is a
human-validated 500-instance subset and publishes an apples-to-apples
mini-SWE-agent configuration. Terminal-Bench evaluates end-to-end tasks in a
standardized terminal sandbox. LOLM needs an official run on those exact
harnesses before making a public leaderboard claim.

- SWE-bench Verified: https://www.swebench.com/verified.html
- SWE-bench submission process: https://www.swebench.com/submit.html
- Terminal-Bench/Harbor: https://github.com/harbor-framework/terminal-bench-2
- OpenAI Codex evaluation disclosure: https://openai.com/index/introducing-codex/

Docker was not installed on this Mac during this run, so Terminal-Bench 2.0 was
not locally runnable. Public percentages from different agents, model versions,
task exclusions, scaffolds, and budgets are not copied into this report as if
they were directly comparable.

## Remaining proof gates

1. Re-run the same six tasks for at least three trials per agent.
2. Re-run Codex after the recorded usage limit clears, without changing tasks,
   timeouts, prompt hashes, or graders.
3. Add authenticated Claude Code and Gemini CLI tracks if available.
4. Package LOLM as a Harbor installed-agent adapter and run Terminal-Bench 2.0
   on a Docker-capable host.
5. Run mini-SWE-agent/SWE-bench Verified with a frozen LOLM release and publish
   the complete prediction log rather than a selected subset.

Until those gates are complete, the defensible statement is: **LOLM passed this
reproducible six-task hidden-test pilot 6/6 with a user-owned backend and active
NFET; frontier-agent parity is not yet proven.**
