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

## 2.1.0 regression check, 2026-09-10

Twelve tasks on a frozen 2.1.0 snapshot. **Five scored, five passed, no
regressions.** The other seven never reached a verdict: Gemini spent its daily
allowance partway through (4) and returned HTTP 503 "experiencing high demand"
on three more. Those are excluded as `usage_limit` and `provider_unavailable`
rather than counted against the build.

Two classification bugs surfaced here and are fixed. A 503 was scored as a
model FAIL — the needle list had `429` but never `503` — and a transient
upstream outage is now named `provider_unavailable` rather than folded into
`usage_limit`, because a provider having a bad minute is not a user running out
of allowance. Correcting that over-corrected: three runs whose hidden grader
*passed* were then excluded because their receipt happened to mention a 503. A
run that produced a passing artifact demonstrably worked, so a passing grader
now always counts, whatever noise the receipt carries.

## Step efficiency — diagnosed, not yet measured

Reading the Sept ablation traces: eight of twelve runs spent the entire
twelve-step budget, mean 11.2 steps. The traces show why. `graph_topo` wrote
the same file five times; `semver` ran a passing test at step 11 and then
patched the file again at step 12. The model issues one tool call per turn and
has no signal that it is done or that turns are finite, so it polishes until
the budget runs out — which is what failed `pkg_calc`.

2.2.0 states the step budget in the system context, tells the model to batch
independent calls and to stop once verification has actually passed, and warns
once when two steps remain. **That change is not yet measured end to end.** A
clean A/B needs the same tasks on both builds, and on the day it shipped every
hosted tier was unavailable — Gemini 404/exhausted, Groq capped at 8k
tokens/minute which a multi-step task exceeds, Cerebras returning 402, and the
local models too slow on a contended host. The loop behaviour is covered by a
test; the step-count claim is not made until it can be run.
