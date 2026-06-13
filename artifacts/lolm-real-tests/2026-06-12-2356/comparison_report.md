# LOLM / NFET Real Testing Mandate — Comparison Report

- Runs: **26** (8 baseline, 18 NFET) — every run is a REAL local generation (qwen3_0_6b_smoke + graft, MPS), not a replay.
- Plus 1 live production frontier run (Llama-3.3-70B via Workers AI) and 1 forced-fallback (T6) run, captured separately.

## A. Is the controller invoked + logged during generation? (mandate Q1)
- **18/18 NFET runs produced graft telemetry frames** (per-token entropy/drift/gate/regime + control logits). Controller invocation rate: **100%**.
- Live production run: 84 + 116 telemetry frames across 2 segments; the **trained control head** chose `retrieve` (source=head, p=0.57).
- Verdict: **YES — the controller runs during generation and is logged.**

## B. Do decisions change the generation path + get consumed? (mandate Q2)
- Control actions (retrieve/verify/branch) fired & consumed in **2/18** local NFET runs; `nfet_finalize`/action consumed in **3/18**.
  - T2: ['retrieve']
  - T8: ['verify']
- Live production: `retrieve` fired and injected 2 evidence rows into the next segment (changed_text=true).
- For the **local** path, the graft also rewrites token logits inline (server.py projects corrected_hidden through the LM head before sampling) — see text divergence in section C.
- Verdict: **YES when control fires — but it fires in a MINORITY of runs.** Most runs stay `continue`→`finalize` (honestly reported as `no_control_visible`).

## C. Baseline (graft OFF) vs NFET (graft ON), matched settings — does it change behavior?
| test | baseline answer (first 70) | NFET answer (first 70) | word-overlap |
|---|---|---|---|
| T1 | 'The sky appears blue because of the way light interacts with the atmos' | 'The sky appears blue because of the way light interacts with the atmos' | 0.423 |
| T2 | 'SATISFIABLE' | 'The verdict is UNSATISFIABLE. A proof by contradiction is provided.' | 0.0 |
| T4 | 'The motion sensor recorded movement, which implies that Morgan entered' | 'first invalid step, why invalid, counterexample, corrected theorem: st' | 0.03 |
| T9 | 'The ball costs $0.50. The one-line check is: $0.50.' | 'The bat and a ball cost $1.10 in total. The bat costs $1.00 more than ' | 0.25 |

Low word-overlap on matched prompts (e.g. T1 sky-blue) confirms the graft materially changes local generation — it is in the path, not decorative.

## D. Quality / correctness per test (mandate Q3) — task contract checks, NOT telemetry
| test | what it proves | baseline pass | NFET pass | notes |
|---|---|---|---|---|
| T0 | controller reachable+logged | n/a | n/a | |
| T1 | NFET changes behavior | n/a | n/a | |
| T2 | formal logic UNSAT | 1/2 | 1/2 | |
| T3 | false-proof audit | n/a | 1/2 | |
| T4 | underdetermined (no overclaim) | 0/2 | 0/2 | |
| T5 | 700w 6-char contract | n/a | 0/2 | |
| T7 | 5 sections, no repetition | n/a | 0/2 | |
| T8 | retrieval actually used | n/a | 2/2 | |
| T9 | bat&ball confidence trap | 0/2 | 0/2 | |

## E. Honest reading of D
- The local **0.6B is weak/inconsistent on hard reasoning** (T2/T3 ≈ chance on binary verdicts; T4 overclaims a culprit in BOTH modes; T5/T7 fail long-form contracts; T9 falls for the bat&ball trap all 4 times).
- **The one task the architecture clearly helps: T8 retrieval grounding — 2/2** (the agent retrieved/verified and used the seeded note). That is exactly the value the control+evidence loop adds.
- **Control firing did NOT reliably improve correctness vs baseline at 0.6B scale.** Quality improvement from control is **NOT PROVEN** here.
- The production **70B** answered the same bat&ball prompt correctly ($0.05) — capability is the frontier model's; the NFET layer adds measured uncertainty, logged control, retrieval, and honest receipts on top.

## F. Model + fallback honesty (mandate Q4)
- Live production receipt: `model_used = workers_ai:llama-3.3-70b-instruct-fp8-fast` (real 70B). No fallback masquerade.
- T6 forced-outage: run fell back to local 0.6B and recorded `fell_back_from=frontier`, `fallback_reason=...`. **Gap found + fixed:** `build_receipt` now emits a `model` layer + `quality_warning` so the receipt itself discloses 'this was not a frontier result'.
- Receipts separate telemetry from task success (`control_visible` ≠ `task_passed`; `nfet_activity_observed_but_task_failed` exists).

## G. Failure-label tally (all runs)
- `formal_reasoning_failed`: 6
- `converse_fallacy_detected`: 3
- `required_facts_missing`: 2
- `length_requirement_failed`: 2
- `required_sections_missing`: 2
- `invalid_inverse_detected`: 1
- `task_contract_failed`: 1

## H. Reductions vs mandate (honesty about coverage)
- Repeats: **2x** per (test,mode), not the mandate's 3x — to fit MPS runtime; each is a real run. T0/T1 also corroborated by a separate CPU smoke.
- Baseline-vs-NFET controlled comparison was run on the **local** path (fully reproducible). The **frontier** path's quality-vs-baseline was NOT isolated (would need a graft-off 70B run); production evidence shows control FIRES on the 70B path but not that it IMPROVES the 70B answer.
