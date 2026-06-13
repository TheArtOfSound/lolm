# LOLM/NFET TEST VERDICT

_Produced under the LOLM/NFET Real Testing Mandate. Every number traces to a real
run in this folder (`baseline_runs.jsonl`, `nfet_runs.jsonl`,
`live_production_run_frontier.sse.txt`, `t6_fallback_disclosure.json`). Nothing
was faked; failures are recorded as failures._

| Field | Verdict |
|---|---|
| **Architecture status** | **PARTIAL** — active control is real (not observer-only, not unwired), but fires in a minority of runs and its quality lift is unproven |
| **Baseline comparison validity** | **VALID** for the local path (graft OFF vs ON, matched model/temp/top_p/tokens/system/contract). **INVALID/not-isolated** for the frontier 70B path (no graft-off 70B run) |
| **Model honesty** | **PASS** — live production receipt reports `model_used = workers_ai:llama-3.3-70b-instruct-fp8-fast`; no fallback masquerades as 70B |
| **Fallback disclosure** | **FAIL → PASS (fixed this session)** — the run recorded the fallback, but the receipt did not surface it; `build_receipt` now emits a `model` layer + `quality_warning` |
| **Contract checking** | **PASS** — `check_contract` does real structural validation (sections, counts, fact coverage, duplicate n-grams); it caught overclaims (T4), missing characters (T5), missing sections (T7) |
| **Quality improvement (control vs baseline)** | **NOT_PROVEN** at 0.6B scale — control firing did not reliably beat baseline on hard reasoning. One exception: **T8 retrieval grounding 2/2** |
| **Required claim downgrade** | **YES** — calibrate "measured uncertainty *steering* frontier-quality prose" to what is proven (below) |
| **Production blocker** | **NO** — the demo works, the 70B answers are correct, receipts are honest. Marketing copy needs calibration, which is not a blocker |

## Top evidence
1. **Generation path** — `local_ui/nfet_agent.py:619` (`run_events`): segment → `policy.decide(control_logits, head_trained)` → retrieve/verify/branch/finalize that reshape the next segment. Frontier telemetry via `local_ui/claude_reasoner.py:47` (`telemetry_traces_from_text`, a real `backbone→graft→head` forward pass). Local token-level graft: `local_ui/server.py:308` projects `corrected_hidden` through the LM head before sampling.
2. **Controller invoked** — 18/18 local NFET runs produced graft telemetry frames (100%). Live production: 84+116 frames over 2 segments.
3. **Decision consumed** — live production run: trained head chose `retrieve` (source=head, p=0.57, `head_probs=[0.28,0.57,0.14,…]`); it injected 2 evidence rows; `actions_taken=true`, `changed_text=true`. Local: T2 `retrieve`, T8 `verify` fired and were consumed.
4. **Baseline vs NFET differs** — matched-setting local runs diverge (T2 baseline "SATISFIABLE" vs NFET "UNSATISFIABLE", word-overlap 0.0; T4 overlap 0.03), proving the graft is in the path, not decorative.
5. **Honest failure** — local 0.6B fails the bat&ball trap 4/4 (`formal_reasoning_failed`); the production 70B gets it right ($0.05). Capability is the frontier model's; NFET adds measured uncertainty, logged control, retrieval, and honest receipts.

## Blunt summary
LOLM/NFET is **real and wired in, not a decoration** — the controller runs on every
generation, the trained head makes decisions the loop actually consumes (retrieve
evidence, verify, stop), and on the local model the graft demonstrably rewrites the
tokens. But it is **not** the "the math makes the 70B smarter token-by-token" story:
on the frontier path the graft is a **post-hoc, segment-level monitor/controller**,
and control actions fire in a **minority** of runs. At 0.6B scale the model is weak on
hard reasoning and control does **not** measurably improve correctness — the clear win
is **retrieval grounding (T8)**. The receipts are honest (they separate telemetry from
task success and, after this session's fix, disclose fallback). **Net: keep the
"measures its own uncertainty and takes logged, inspectable control actions" claim;
drop or qualify any "steers/​improves frontier-quality prose" claim until a
graft-off-vs-on 70B comparison proves a quality lift.**

## Required claim calibration (mandate §11–12)
| Current copy | Proven? | Replace with |
|---|---|---|
| "measured uncertainty **steering** frontier-quality prose" | No (quality lift unproven; frontier control is segment-level) | "measures its own uncertainty per token and takes logged control actions — check notes, verify, or stop" |
| "Llama 70B writes, LOLM measures its uncertainty and **controls**" | Partly (control fires, minority) | keep, but add "control acts at segment boundaries; it does not steer the 70B token-by-token" |
| "streams per-token entropy/drift/gate/regime + control logits" | **Yes** | keep |
| "trained control head armed" | **Yes** (p=0.57 fired in prod) | keep |

## Honest coverage limits
- Repeats were **2×** per (test,mode), not the mandate's 3× — to fit MPS runtime (~40–210 s/run). Each is a real run; T0/T1 corroborated by a separate CPU smoke.
- The frontier path's quality-vs-baseline was **not isolated** (no graft-off 70B run); production proves control *fires*, not that it *improves* the 70B answer.
