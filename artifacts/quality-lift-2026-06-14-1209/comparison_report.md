# Quality-lift proof — gated retrieval grounding (2026-06-14)

**Question the contribution matrix left open:** control fires and is consumed, the
graft changes tokens, the telemetry is real — but does any of it make the *answer
better*? ("quality vs baseline: unproven.")

## Design (matched, deterministic)
Same 70B writer (`workers_ai` / Llama-3.3-70B), same prompts, same settings. The
**only** variable is whether the NFET controller may retrieve seeded memory.
- **NEEDS** (8): ask for a fact present only in seeded memory — the writer cannot
  know it (made-up entities/values, e.g. "the Zerelium reactor's calibration
  constant is 7731"). Score = final answer contains the exact value.
- **KNOWS** (4): common facts the writer already knows (triangle sides, boiling
  point, days/week, 12×12). Selectivity check — control must not break these.

## Results

| controller | NEEDS correct | NEEDS retrieve-rate | KNOWS correct | KNOWS retrieve-rate |
|---|---|---|---|---|
| **baseline** (retrieval off) | **0/8 (0.00)** | — | 4/4 (1.00) | — |
| **conservative NFET** (default thresholds) | 2/8 (0.25) | 0.25 | 4/4 (1.00) | **0/4 (0.00)** |
| **eager NFET** (entropy_spike_z=0.45) | **7/8 (0.875)** | 0.875 | 4/4 (1.00) | 0.50 |

## What is proven
- **Causal correctness lift.** Baseline grounds **0/8** facts it can't know. With the
  controller's retrieval enabled, correctness rises to **2/8 → 7/8** depending on how
  eagerly it retrieves. The lift is large and attributable to the control action,
  not the model (same writer throughout).
- **Retrieve ⟺ correct.** Across both NFET runs, every retrieval produced a correct
  grounded answer; every miss was a *non-retrieval*. The mechanism is clean.
- **No correctness regression on knowns.** KNOWS stayed 4/4 in every condition —
  retrieval, even when wasteful, did not corrupt answers the model already had.

## Honest caveats (what is NOT claimed)
- **Threshold trades recall vs. retrieval-efficiency, not correctness.** The eager
  controller over-retrieves on 2/4 knowns (wasteful, harmless). The conservative
  controller is perfectly selective (0/4) but under-recalls (2/8). A balanced
  threshold is future tuning; it does not affect the proven correctness lift.
- **Broader reasoning-quality lift remains open.** This proves grounding (knowledge
  the writer lacks). It does *not* prove the controller improves hard *reasoning*
  the model could do unaided — that category is unaffected by retrieval.

## Verdict
**PROVEN (scoped): NFET gated retrieval lifts answer correctness 0 → up to 88% on
facts the writer cannot otherwise know, with zero correctness regression on knowns.**
General reasoning-quality lift: still open.

Artifacts: `results.json` (conservative), `../quality-lift-eager-*.json` (eager).
Reproduce: `scripts/prove_quality_lift.py`, `scripts/quality_lift_eager.py`.
