# NFET Fastpath: Controlled Experiment 01

This branch does not change the default controller, train a new foundation model,
or establish a performance improvement. It adds outcome signals and two opt-in
ablations for paired same-model measurement.

## Flags

- Default: existing NFET window and completion behavior.
- LOLM_NFET_FAST_MONITOR=1: use a 48-token NFET replay window for coding
  and 32 tokens for asking/documents instead of the original 128/64.
  Experimental: long-range uncertainty signals may be missed.
- LOLM_STRICT_ACCEPTANCE=1: for code tasks that changed files, require a
  recognizable successful test command before considering them checked.
  A passing test does NOT prove task correctness or test coverage.

## Timing and evidence

The existing eventSink receives agent.outcome.evidence with elapsed_ms,
provider_calls, provider_ms, nfet_calls, nfet_ms, nfet_analyzed_tokens,
changes_count, commands_count, outcome_evidence, strict_acceptance and
nfet_fast_monitor. New outcome events contain no prompt, command, path,
stdout, API key or raw user text. Other existing tool events may contain
raw details and must be handled separately.

## Paired evaluation protocol

1. Hold provider/model, inference settings, permissions, machine, and prompts
   constant. Use isolated copies of repositories for state-changing tasks.
2. Run 20 or more matched tasks under baseline and fast monitor. Randomize
   order to control for cold-start, cache and machine load.
3. Compare paired wall-clock latency, NFET inference time, replayed tokens,
   completed tasks, retried calls, failed tests, false completions and
   unverified high-risk actions. Bootstrap paired confidence intervals.
4. Include trivial, complex, ambiguous and adversarial tasks; use fresh
   holdouts and independent acceptance checks.
5. Change the default only if measured end-to-end time decreases without
   degraded success, correctness, or safety. Separate one-time model boot
   from steady-state overhead.
6. Train future LOLM controllers only on opt-in, redacted, independently
   validated outcome data. These signals are a first step, not training labels
   that magically guarantee success.

## Testing

From repository root (Node 20 or 22 with workspace dependencies installed):

    npm test --workspace lolm-cli

Standalone evidence tests:

    node --test clients/cli/test/outcome-evidence.test.mjs

The legacy runner.verified behavior remains unchanged by default.
