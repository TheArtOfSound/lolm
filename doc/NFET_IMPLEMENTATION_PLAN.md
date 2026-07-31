# NFET Implementation Plan — Closed-Loop Control for LOLM

**Status:** living engineering document  
**Mandate:** no “years ahead” claim without matched-baseline proof  
**Repo audit date:** 2026-07-31  

---

## 0. Honest audit: where we are today

| Path | Verdict | Evidence |
|------|---------|----------|
| **Chat / dialog agent** (`local_ui/nfet_agent.py`) | **Partially wired active control** | At **segment boundaries**, `policy.decide` → `_do_retrieve` / `_do_verify` / `_do_branch` / `_do_finalize` — actions **are consumed**. Not mid-token. Budgets and cooldowns apply. |
| **Coding agent** (`local_ui/code_nfet.py` + `code_agent.py`) | **Partially wired active control** | After each RUN: NFET (graft or synthetic) → force verify / branch / retrieve / block finalize. Repair ensemble + contract probe consume decisions. |
| **Core token generation** (Transformer/SSM forward) | **Not gated by NFET action** | Graft produces telemetry + residual correction; manifestation gate fuses streams. Controller does **not** change the next-token path mid-decode (no deliberate/reset/compress inside the LM loop). |
| **Control plane** (`lolm/control/*`) | **Observer + decision packet** | `decide()` builds `DecisionPacket`; receipts hash decisions. Separate from `nfet_policy` five-action loop. |
| **Coding head** (`runs/nfet_controller/code_head.pt`) | **Trained policy overlay** | Val acc ~0.91 on synth+receipts. Does **not** prove task-quality lift vs matched baseline. |
| **Matched ΔQ proof** | **Not established** | AB benches measure coding harness quality. No published plain-LOLM vs observer-NFET vs active-NFET ΔQ with compute cost. |

**Single-line verdict:**

> **Partially wired active control at the agent loop (segment / run), observer-plus-telemetry at the token level, not a fully closed multi-timescale cognitive controller.**

Telemetry, confidence maps, and QEV-style receipts prove **provenance**, not **quality**. Quality requires the experiment in §32 of the product brief.

---

## 1. Architecture (text diagram)

```
                         USER / TASK / CONTRACT
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         LOLM CORE (representation)                   │
│  x_t ──► [ Surface Transformer T ] ──► h_t                          │
│            │                                                        │
│            ▼                                                        │
│         [ Latent SSM S ]  z_t = S(z_{t-1}, h_t)                     │
│            │                                                        │
│            ▼                                                        │
│         [ Regime R ]  ρ_t                                           │
│            │                                                        │
│            ▼                                                        │
│         [ Memory M ]  read/write gated                              │
│            │                                                        │
│            ▼                                                        │
│         [ Manifestation gate g_t ]                                  │
│            r_t = g⊙h + (1-g)⊙z + …                                  │
│            │                                                        │
│            ▼                                                        │
│         [ Decoder ]  P(x_{t+1} | r_t)                               │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                    per-token / per-segment telemetry
                    (entropy, drift, gate, regime, …)
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      NFET CONTROL PLANE                              │
│  State estimator → s_t                                              │
│  Policy π(a|s)   → a_t ∈ ActionSpace                                │
│  Action executor → MUST change generation path                      │
│  Contract checker → task success ≠ internal calm                    │
│  Receipt / QEV   → seal what was decided + consumed                 │
└─────────────────────────────────────────────────────────────────────┘
         │ continue │ retrieve │ verify │ branch │ deliberate │
         │ tool │ compress │ reset │ stop │ finalize              │
         └────────────────────┬──────────────────────────────────┘
                              ▼
                    next segment / tool / stop
```

**Core transformation:**  
LOLM without NFET **learns** latent state.  
LOLM with NFET **uses** latent state to **govern** computation.

---

## 2–6. Representation components (existing + target)

| # | Component | Today | Target |
|---|-----------|-------|--------|
| 2 | Surface Transformer | HF backbone / LOLM decoder | Unchanged role: local semantics, fluent tokens |
| 3 | Latent SSM | Graft selective SSM / GRU debug | Must become **causally required** for control decisions, not decorative residual |
| 4 | Persistent memory | `memory_store`, research memory | Write policy under NFET; suppress stale / poisoned entries |
| 5 | Regime | Graft regime head | Explicit ρ_t labels for fluent / deficit / thrash / tool-need / finalize-ready |
| 6 | Manifestation gate | Learned per-dim gate in graft | Regime- and action-conditioned gate (coding vs prose) |

Fusion (simplified, as in brief):

\[
h_t = T(x_{\le t}),\quad
z_t = S(z_{t-1}, h_t),\quad
g_t = \sigma(W_g[h_t;z_t]),\quad
r_t = g_t \odot h_t + (1-g_t)\odot z_t
\]

---

## 7. NFET state vector \(s_t\)

**Implemented scaffold:** `lolm/control/state_vector.py`

| Symbol | Name | Measurement (v1) | Calibration |
|--------|------|------------------|-------------|
| \(u_t\) | uncertainty | mean graft entropy / synthetic entropy | rolling z vs run baseline |
| \(d_t\) | drift / contradiction | lag-1 hidden drift; assert/traceback as proxy | std floors |
| \(n_t\) | novelty | 1 − overlap with recent stdout/draft | [0,1] |
| \(m_t\) | memory relevance | hit rate of retrieved notes used | retrieval_report |
| \(v_t\) | verification need | contract fail, thrash, high drift+entropy | binary + continuous |
| \(r_t\) | repetition risk | n-gram / segment overlap | [0,1] |
| \(q_t\) | task-quality estimate | green_runs / (green+fail); contract ok | [0,1] |
| \(b_t\) | remaining budget | 1 − steps/max_steps | [0,1] |
| \(c_t\) | contract pressure | missing symbols, probe fail | {0,1}+ |
| \(\rho_t\) | regime id | argmax heuristic on \(s_t\) | discrete |

Each field has: definition, unit, floor, and whether graft or proxy.

---

## 8. Action space

**Canonical set (v1, implementable now):**

| Action | Must change generation path |
|--------|-----------------------------|
| `continue` | emit next segment / next RUN |
| `deliberate` | extra latent re-read / second pass before emit (v1: force contract probe) |
| `retrieve` | inject memory / web / past receipts |
| `branch` | multi-candidate ensemble; keep verified winner |
| `compare` | score candidates against contract |
| `verify` | tests / contract probe / py_compile |
| `retry` | discard last segment; re-prompt with error |
| `compress` | summarize workspace into identity/context (session) |
| `reset` | clear thrash state; full FILE rewrite authorized |
| `tool` | sandbox run / external tool |
| `stop` / `refuse` | no finalize if contract red or unsafe |
| `finalize` | DONE only if contract + allow_finalize |

**Not “control” if only logged.** Executor must return `consumed: true` with side effects.

---

## 9. Controller policy

Three layers (priority high → low):

1. **Hard guards** — thrash → branch; contract red → verify; red run → never finalize; safety refuse  
2. **Trained coding head** (`code_head.pt`) when \(p \ge \tau\)  
3. **Calibrated heuristic** (`NFETControlPolicy` z-scores)  
4. **Optional graft control logits** when `head_trained` on dialog graft  

Objective (conceptual):

\[
a_t = \arg\max_a \mathbb{E}[\Delta Q(a) - \lambda C(a) - \mu R(a) \mid s_t]
\]

v1 uses discrete rules + learned classifier as a stand-in for \(\pi_\theta\).

---

## 10. Action executor

**Module:** `lolm/control/action_executor.py`

```text
execute(action, context) -> ExecutionResult{
  consumed: bool,
  side_effects: [...],
  evidence: [...],
  error: optional
}
```

Wiring targets:
- Dialog: already in `NFETAgent._do_*` — wrap with unified result type  
- Code: `CodeAgent` forces branch/verify/retrieve/finalize gates  

---

## 11. Contract checker

**Module:** `lolm/control/contract.py`

- Parse task for paths, symbols, examples, rejects (reuse code_agent helpers)  
- Run probes in sandbox  
- `internal_confidence ≠ task_success` — contract can override calm finalize  

---

## 12. QEV / receipt system

Today: `code_receipts` ledger + control receipts + vault seal.  

**Schema extension (v1):** every receipt includes:

```json
{
  "controller_version": "...",
  "nfet": {
    "mode": "graft|synthetic|code_head",
    "actions": [{"a":"verify","consumed":true,"ms":12}],
    "state_snapshot": {...},
    "contract": {"ok": false, "reasons": [...]}
  }
}
```

QEV seals integrity of this record — **not** answer correctness.

---

## 13. Multi-timescale control

| Scale | Cadence | v1 implementation |
|-------|---------|-------------------|
| Token | every N tokens | telemetry only (measure) |
| Segment | draft segment / RUN | **active** decide+execute |
| Task | before DONE | contract + allow_finalize |
| Session | conversation / project | memory promote, compress (partial) |

---

## 14–18. Training

| Stage | Method | Status |
|-------|--------|--------|
| 14.1 Bootstrap | distill heuristic → head (hidden weights zeroed) | **done** (chat + coding heads) |
| 14.2 Outcome labels | receipts → weak labels | **partial** (`mine_code_receipts`) |
| 14.3 Replay | backbone+graft full features | **script exists**, not continuous on prod |
| 15 Losses | CE class-weighted + sample weights | **done** for heads |
| 16 Trajectory data | log `(s_t, a_t, consumed, ΔQ proxy)` | **scaffold** `trajectory.py` |
| 17 Counterfactual | offline a, estimate ΔQ offline | **stub** |
| 18 Verifier RL | reward on contract/hidden-test success − λ cost | **not started** |

---

## 19. Inference pseudocode (target)

```
state = init()
while not done and budget:
    segment = generate(state)           # surface+latent+gate
    s = estimate_state(segment, sandbox_evidence)
    a = policy(s)                       # guards > head > heuristic
    result = executor.execute(a, state) # MUST mutate path
    seal_partial(s, a, result.consumed)
    if a == finalize and contract.ok:
        break
return answer, receipt
```

---

## 20. Schemas

See `lolm/control/schemas.py` (JSON-serializable dataclasses).

---

## 21. Repository structure (target)

```
lolm/
  model.py, ssm.py, gate.py, regime.py, memory.py, nfet_graft.py
  nfet_policy.py, nfet_controller_train.py, code_nfet_train.py
  control/
    nfet.py, signals.py, decision_packet.py, receipt.py
    state_vector.py      # NEW
    action_executor.py   # NEW
    contract.py          # NEW
    trajectory.py        # NEW
    schemas.py           # NEW
local_ui/
  nfet_agent.py, code_agent.py, code_nfet.py
scripts/
  train_nfet_controller.py, train_code_nfet.py
  nfet_baseline_harness.py  # NEW — §32 experiment
docs/
  NFET_IMPLEMENTATION_PLAN.md  # this file
tests/
  test_nfet_*, test_code_nfet*, test_control*
```

---

## 22–25. Baseline harness & metrics

**Script:** `scripts/nfet_baseline_harness.py`

Arms:
1. Plain (no NFET decisions)  
2. Observer-only (decide + log, no execute)  
3. Active NFET (decide + execute)  
4. External agent loop (optional later)  

Metrics:

\[
\Delta Q = Q_{\text{NFET}} - Q_{\text{baseline}},\quad
\Delta E = \frac{Q_{\text{NFET}}}{C_{\text{NFET}}} - \frac{Q_{\text{baseline}}}{C_{\text{baseline}}}
\]

\(Q\): pass rate / contract rate / hidden-test rate  
\(C\): wall seconds, model calls, tokens  

**Success criterion:** active arm improves \(Q\) with attributable control and acceptable \(C\); replicates; survives holdout; ablations identify components.

---

## 26–29. Failure modes & safety

| Failure | Control |
|---------|---------|
| Controller thrashing | cooldown, max actions/run, branch budget |
| Memory poisoning | write gates, identity promotion rules, forget API |
| Overclaim | contract probe, honesty detectors, refuse finalize |
| Decorative latent path | ablations; control only via latent-derived \(s_t\) |
| Cost blowup | λ cost in policy; segment caps |
| Safety | refuse action; no network in sandbox by default |

---

## 30. Six-month build sequence

| Month | Deliverable | Exit criteria |
|-------|-------------|----------------|
| **M1** | Unified state vector + executor + contract + trajectory log; baseline harness v0 | Harness runs 3 arms on coding tasks; actions mark `consumed` |
| **M2** | Active coding NFET complete; dialog executor unified; AB n=60 active vs plain | ΔQ coding published or honest null result |
| **M3** | Replay training continuous; counterfactual offline eval | Head improves holdout action accuracy under outcomes |
| **M4** | Token-timescale deliberate/reset hooks (limited); multi-timescale budgets | Mid-generation intervention changes behavior on trap tasks |
| **M5** | Verifier-driven RL lite; tool action expansion | Efficiency ΔE ≥ 0 on cost-sensitive suite |
| **M6** | Public proof pack: ablations, compute, failure cards; product claims only if proven | Ship or retract “control improves quality” |

---

## Scientific hypothesis (falsifiable)

> A model with persistent latent state and a **trained closed-loop controller** produces more **verified useful task performance per unit compute** than the same model under static autoregressive inference.

## Commercial possibility (conditional)

> Smaller local models behave like **disciplined cognitive systems** if control is real — not weak chatbot skins.

## What we refuse to claim until proven

- “Years ahead of frontier models”  
- Quality from confidence badges or NFET logos  
- That graft residual alone is strategic reasoning  
- That coding head val acc equals task success  

---

## Immediate implementation (this PR wave)

1. This document  
2. `state_vector.py`, `action_executor.py`, `contract.py`, `trajectory.py`, `schemas.py`  
3. `scripts/nfet_baseline_harness.py`  
4. Wire executor consumption flags into code path  
5. Tests for state + executor + harness dry-run  
