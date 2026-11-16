# Security-regime lab — baseline results (2026-11-15)

## Reproduction

    python -m unittest discover -s tests -p 'test_security_*.py' -v
    python -m lolm.security_research.cli benchmark

- 24 focused unit tests passed locally (Python 3.13).
- Four seeded synthetic samples: 17, 37, 53, 101.
- Modes evaluated on identical event streams per seed (matched comparison).
- Events simulate one fictional authentication-abuse sequence, a privilege
  change/export, repeated remote-token usage and a spoofable ARTEX
  enrichment User-Agent.
- Each sample has 17 labeled suspicious actions and 140 benign filler events.
  The suspicious-event schedule is identical across seeds; only benign
  filler event types change.

| Mode | Precision | Recall | F1 | Event-level FPR |
|---|---:|---:|---:|---:|
| Rules | 1.0000 | 0.5882 | 0.7407 | 0.0000 |
| Regime shift heuristic | 1.0000 | 0.2941 | 0.4545 | 0.0000 |
| OR hybrid | 1.0000 | 0.5882 | 0.7407 | 0.0000 |

**Result: hybrid shows no improvement over the rules baseline.**
The shift heuristic is worse on this toy stream. Zero observed false
positives is a dataset weakness, not a deployment-quality claim.
A trained LOLM checkpoint was NOT part of this experiment.

## Conclusions explicitly not supported

- This is not real-world intrusion-detection accuracy.
- A matching ARTEX User-Agent does not establish ARTEX attribution.
- There is no demonstrated neural LOLM/NFET benefit.
- Four deterministic seeds are not four independent real intrusions.
- Unit prompt-injection tests are not sufficient to establish robust safety.

## Next empirical gate

1. Ingest rights-cleared, diverse OCSF authentication datasets.
2. Preserve actor pseudonymization and separate incident ground-truth labels.
3. Split by scenario/organization/time, never overlapping event rows.
4. Compare rules, shift, hybrid and a frozen neural LOLM observer on identical
   test data with matched compute/latency budgets.
5. Report false alerts per host-day, time to first incident alert,
   analyst time saved and failure modes.
6. Attribute any gain to LOLM only after rigorous ablations and held-out
   performance checks.


## Phase 2 — adversarial synthetic stress results

Eight fictional scenarios (three suspicious, five benign), 109 events.
Benign lookalikes: legitimate lockout, approved migration, spoofed User-Agent,
ordinary remote automation.

| Method | Precision | Event recall | Event FPR | Incident recall | Benign cases alerted |
|---|---:|---:|---:|---:|---:|
| Rules | 0.4286 | 0.2400 | 0.0952 | 0.3333 | 3/5 |
| Shift | 0.5000 | 0.0800 | 0.0238 | 0.3333 | 1/5 |
| Hybrid | 0.4286 | 0.2400 | 0.0952 | 0.3333 | 3/5 |

**Negative result:** The hybrid does not beat the rules baseline and is
vulnerable to benign lookalikes. The rule-based detector misses the
low-and-slow fictional scenario. These values are designed to reveal
failure modes and MUST NOT be presented as real-world accuracy.

## Phase 2 — LOLM/NFET observer validation

An offline token-to-event telemetry bridge, manifest integrity checks,
optional independently pinned local checkpoint byte verification, training
vs test separation, and reference/calibration splitting were implemented.

**No trained LOLM neural checkpoint was executed.** Synthetic trace tests
cannot demonstrate a model advantage. Trace hashing is not proof of inference
provenance. Strict next gate: execute a frozen checkpoint on responsibly
sourced, independently labeled, temporally held-out security data, with
matched traditional baselines.


## Phase 2.1 capture module

The synthetic-only generation-loop adapter and checkpoint-pinned export CLI
are implemented. Five fake-generator tests were added. Passing these tests
does not demonstrate checkpoint inference; **no trained LOLM checkpoint was
loaded** in this phase.


## Phase 3 — negative control and original LOLM capture adapter

The deliberately uninformative synthetic event-aligned trace produced
0/25 suspicious-event detections, no false alerts, and 7/7 shuffled
controls at least as discriminative. The descriptive scenario permutation
p-value is 1.0 across 56 assignments; this is NOT evidence about a
trained LOLM checkpoint.

A native LOLM-304M tensor extraction adapter and SHA-pinned strict loader
were implemented and unit tested with synthetic PyTorch tensors. No actual
304M checkpoint was loaded or benchmarked in this session; performance
claims remain prohibited. The focused local suite comprises 69 tests.
