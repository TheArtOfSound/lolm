# Hard adversarial eval — 0.6b-recheck

**6/6 cases passed** · avg 72.8s/run

| category | pass | cases |
|---|---|---|
| multilingual | 2/2 | ml1, ml2 |
| profile | 4/4 | prof1, prof2, prof3, prof4 |

## Failures
None — every mechanism invariant held.

## Per-case detail
| case | cat | ok | profile | ended | verdict | s | chars |
|---|---|---|---|---|---|---|---|
| prof1 | profile | ✓ | question | repetition_stall | changed_but_controls_quiet | 144 | 471 |
| prof2 | profile | ✓ | social | social_direct | social_direct_reply | 17 | 7 |
| prof3 | profile | ✓ | question | repetition_stall | nfet_control_visible | 103 | 116 |
| prof4 | profile | ✓ | social | social_direct | social_direct_reply | 32 | 107 |
| ml1 | multilingual | ✓ | question | repetition_stall | nfet_control_visible | 77 | 165 |
| ml2 | multilingual | ✓ | question | repetition_stall | changed_but_controls_quiet | 64 | 29 |