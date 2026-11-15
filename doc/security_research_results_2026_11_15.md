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
