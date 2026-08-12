# Customer CLI cross-agent benchmark

This suite evaluates the actual terminal products rather than calling their
underlying model APIs. Every task runs in a fresh temporary directory. Seed
files are copied in first; the hidden grader is written only after the agent has
exited. A grader exit code of zero is the only pass condition.

## The suite

`bench.tasks` is 26 tasks across six tiers: `impl` (exacting semantics and edge
cases), `fix` (seeded multi-file bugs), `refactor` (change the structure, keep
the behaviour), `tdd` (make an existing failing test pass without editing it),
`cli` (a real command line program graded through subprocess calls on stdout and
exit codes), and `package` (build an importable package with a `__main__` entry
point).

Run `python3 bench/validate.py` first. It asserts that every task's reference
implementation passes its hidden test, and that every seeded bug actually fails
it. A hidden test a correct solution cannot pass — or a "fix" task that was
never broken — would make every score meaningless.

## Tracks

| Agent | What it measures |
|---|---|
| `lolm_cerebras` | LOLM on the user's Cerebras `gpt-oss-120b` |
| `lolm_gemini` | LOLM on the control Gemini model |
| `lolm_gemini_nonfet` | the same, NFET disabled — the ablation |
| `lolm` | LOLM on local Ollama |
| `gemini` | Google's own Gemini CLI on the control model |
| `codex` | the installed Codex CLI |
| `claude` | the installed Claude Code CLI |

`lolm_gemini` and `gemini` run the *identical model*, so the gap between them is
a difference between the two scaffolds rather than between two model vendors.
That controlled pair is the only comparison here worth much; a cross-vendor row
mostly measures whichever model is stronger.

## Run

```bash
python3 bench/validate.py
python3 bench/customer_cli/run_cross_agent.py --agents lolm_gemini,gemini --suite full --repeat 3
```

Credentials come from the environment or, on macOS, the Keychain entry LOLM
already uses (`lolm-cli-provider:google`). No key is ever written into this
repository.

Artifacts land in `bench/customer_cli/results/<UTC timestamp>/`:

- `results.json`: machine-readable settings, results, hashes, and summaries
- `REPORT.md`: human-readable scorecard and limitations
- `raw/`: exact agent and hidden-grader stdout/stderr
- `artifacts/`: the files each agent produced

## Reading the output

A run blocked by a missing credential, an expired login, or an exhausted quota
is recorded as `UNSCORED` with the blocker named, not as a model failure. Those
rows are excluded from the pass rate rather than counted as zeros — reporting an
agent that never reached its model as 0% would be dishonest.

A single trial per task has high variance. Use `--repeat 3` or more before
treating small differences as real.

This is a local acceptance benchmark, not an official Terminal-Bench or
SWE-bench submission, and its percentages are not comparable with those public
leaderboards. Those harnesses use their own task sets, sandboxes, and scaffold
configurations; a number produced here only describes this suite.
