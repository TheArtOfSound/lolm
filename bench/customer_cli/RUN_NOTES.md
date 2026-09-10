These are the things the run artifacts cannot tell you.

**The Gemini CLI row is over an easier subset.** Its key exhausted the free-tier
daily quota after `refactor_extract`, so the last eight tasks — the tdd, cli,
package, and remaining impl tier — were never attempted. It went 18/18 on what
it reached. Its 100% and LOLM's 92% are over different task sets. The only
figure worth quoting is the head-to-head over the tasks both agents attempted.

**LOLM ran under a handicap the Gemini CLI did not.** Every LOLM invocation was
capped at `--max-steps 12`. The Gemini CLI has no equivalent externally imposed
turn limit in this harness and stops when it decides it is done.

**`config_merge` is a defect in the benchmark, not in the agent.** Its
instruction said "a value of None on either side is always replaceable", which
reads just as naturally as "an override of None leaves the base alone" — and
that is what the agent implemented. The hidden test encoded the other choice.
`bench/validate.py` cannot catch this class of problem, because the same author
writes the reference implementation and the test, so both share the
misunderstanding. The wording now states both directions with worked examples.
The recorded FAIL above is left exactly as it happened; after the correction the
same task passed 2/2 on Cerebras `gpt-oss-120b`, having failed 2/2 before it.

**`cli_csvstat` is a real miss for this model.** It ran out of turns on
`gemini-3.1-flash-lite`. The same task passes on Cerebras `gpt-oss-120b` at both
a 12-step and a 25-step cap, so the cap was not the limiting factor — the
smaller model needed more turns to get there.

**`json_patch` for LOLM is excluded, not failed.** That invocation hit the same
Gemini quota wall and is recorded as `unparseable_output` because the CLI was
killed before it emitted a receipt.

**The before-fix row is a partial run.** `lolm_cerebras` covers the first 11
tasks only; it was stopped deliberately so the machine was not running two 4B
NFET bridges at once, which was inflating every timing. Its single failure,
`iso_duration`, is the truncated-tool-argument bug: the same task on the same
model and prompt went from 12 steps with 7 failed tool calls and a failing
grader to 4 steps with none and a passing grader after the fix.

**One trial per task.** Nothing here supports a claim about a small difference
between tracks. Three or more trials are needed before the gaps mean anything.

**Not a public leaderboard result.** No Terminal-Bench or SWE-bench number is
reproduced here, and these percentages must not be compared with them. Docker
was not installable on this host — 5.7 GiB free — so neither harness could be
run locally.

## NFET ablation, 2026-09-10

**The controller did not change the score on this suite.** Same model
(`gemini-3.1-flash-lite`), same scaffold, same twelve tasks across every tier,
only the controller toggled: 11/12 with it on, 11/12 with it off. Each side
solved one task the other missed — `fix_cache_ttl` passed only with the
controller, `pkg_calc` only without — which on a single trial is
indistinguishable from noise. Zero interventions fired on either side: after the
1.6.0 change the controller never forced rework on a verified result, and the
trained head returned continue/finalize on the rest.

**What it did change was time.** Median wall time was 81s with the controller
and 60s without. That 21s is the cost of the checkpoints themselves — a few
seconds per decision, several decisions per task. On this model and this suite
the controller is a cost without a measured benefit.

**What this does not settle.** One trial per task. The tasks are ones this
model solves without help, so there was little for a controller to catch; the
open question is whether it earns its keep on tasks the model gets wrong
unassisted, and that needs a harder suite or a weaker model, run more than once.
The build under test was the 1.9.0 CLI, frozen in a snapshot so the working tree
could be edited while it ran (`LOLM_BENCH_SOURCE`).
