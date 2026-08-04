# Persistent Task-State Control

**Category claim:** LOLM is the agent architecture that **does not lose the plot**.

Not “another smarter agent,” not “memory,” not “better reasoning” as a vague pitch.
The product differentiator is **persistent task-state control**: a structured latent
model of the task that is maintained and *used* across time.

## Latent state

\[
z_t = \{ G_t, P_t, W_t, A_t, U_t, F_t, C_t \}
\]

| Symbol | Meaning |
|--------|---------|
| \(G_t\) | Goals and priority ordering |
| \(P_t\) | Plan / dependency steps |
| \(W_t\) | World / workspace model (files, exits, browser) |
| \(A_t\) | Assumptions and commitments |
| \(U_t\) | Uncertainty and unresolved questions |
| \(F_t\) | Failures, contradictions, dead ends |
| \(C_t\) | Completion criteria + evidence |

Update after every observation/action/result:

\[
z_{t+1} = f(z_t, o_t, a_t, r_t)
\]

Policy:

\[
a_{t+1} = \pi(z_{t+1})
\]

Actions: continue, retrieve, verify, branch, finalize (and refuse finalize when
\(C_t\) still has open criteria).

## Implementation

| Piece | Location |
|-------|----------|
| Schema + \(f\) + \(\pi\) + persist | `lolm/control/task_state.py` |
| Code agent inject + DONE gate + receipt | `local_ui/code_agent.py` |
| Visual NFET loop + \(z_t\) | `local_ui/code_routes.py` |
| Technique learning (durable skills) | `local_ui/code_techniques.py` |
| Oort/Flows tactics (140 playbooks → ~740 step tactics) | `lolm/tactics/oort_flows.py` + `oort_flows_catalog.json` |
| NFET measurement (entropy/drift/…) | `local_ui/code_nfet.py`, `lolm/control/state_vector.py` |

NFET, techniques, **Oort/Flows tactics**, receipts, and the cascade are **infrastructure serving \(z_t\)**.
They are not the product claim by themselves.

### Oort + Flows supercharge

- **Library:** Oort (`oortstack.com`) — prompts/workflows  
- **Workspace playbooks:** Flows (`flows.oortstack.com`) — multi-step agent/app/QA harnesses  
- **In LOLM:** vendored catalog injects matching tactics into the agent prompt; strong matches rewrite \(P\) (plan) from the flow’s steps; API `GET /api/demo/code/tactics?q=…`  
- **Rebuild catalog:** `python scripts/import_oort_flows_tactics.py --flows-dir …/src/data/flows`

## Hard rules

1. **Producing output ≠ task complete.** Finalize only when completion criteria have evidence.
2. **State is durable** under `runs/task_state/<task_id>.json` (survives steps; can survive sessions).
3. **π(z)** can force verify/branch even when the last tool exit was 0 (e.g. blank canvas).
4. Receipts seal a compact `task_state` blob for audit (Latent Task Integrity counters).
5. **Active control ≠ task success.** Freeform multi-requirement prompts extract a requirements ledger (`lolm/task_contract.py`). If retrieval is decorative or citations do not entail claims, the receipt is **RED** (`nfet_activity_observed_but_task_failed`), not yellow “unproven.”

### Regression: T10 — Retrieval pollution & contract loss

Aerospace-fiction style prompts (story + real engineering + real/fictional sources + citations + character backstories) must:

- set `has_contract=true` with freeform requirements;
- score retrieval relevance (junk AI-memory ≠ domain evidence);
- fail shallow answers with unsupported `[S#]` citations;
- never report `answer_no_deterministic_fault` when those axes fail.

Tests: `tests/test_task_contract.py`.

### Control governance (post-T10)

| Mechanism | Behavior |
|-----------|----------|
| **Contract gate** | Finalize blocked mid-loop while freeform requirements fail or verify says revise (unless last segment). |
| **Post-revision verify** | After finalize: score requirements → optional repair finalize → recheck; emit `post_revision_verification`. |
| **Retrieval relevance** | Zero relevant hits → strategy note + reformulated target; decorative AI-memory not injected as success. |
| **Confidence split** | `p_action_safe` vs `p_contract_satisfied` vs `p_answer_correct` (not one overloaded `p_correct`). |
| **Seal stages** | `receipt_stage: pre_seal` until `mark_sealed` / `mark_verified` → `envelope_integrity`. |

## Multi-session continuity

Pass `conversation_id` on code/visual APIs. Resume loads the same \(z_t\) after
days or context wipes:

| Path | Role |
|------|------|
| `runs/task_state/<task_id>.json` | Full \(z_t\) |
| `runs/task_state/by_session/conv-*.json` | conversation → task_id index |
| `context_reset=true` | Marks interruption; **keeps** G/P/F/C |
| requirement change mid-task | Merges into G/C without amnesia |

```bash
GET /api/demo/code/task_state?conversation_id=<id>
GET /api/demo/code/task_state/<task_id>
```

## Latent Task Integrity harness

```bash
PYTHONPATH=. .venv/bin/python scripts/lti_harness.py --steps 200 --resets 8
PYTHONPATH=. .venv/bin/python scripts/lti_harness.py --steps 500 --resets 20
```

Arms: **plain** (forget \(z_t\) on wipe) vs **continuous** (persist \(z_t\)).

\[
\text{LTI} = \frac{
  \text{goals retained}
  + \text{constraints respected}
  + \text{dependencies resolved}
  + \text{failures recovered}
  + \text{completion claims verified}
  + \text{premature finalize blocks}
}{\text{compute proxy}}
\]

LOLM wins when \(\Delta\text{LTI} > 0\): after hundreds of steps and interruptions it
still holds the same problem and blocks false completion.

## API

- Task state: `runs/task_state/*.json` + `by_session/`
- Requests: `conversation_id`, `session_id`, `context_reset`
- Receipts include `task_state` when present
- Techniques: `GET /api/demo/code/techniques`
