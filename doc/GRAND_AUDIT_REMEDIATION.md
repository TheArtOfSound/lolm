# Grand Behavioral Reliability Audit — Live Remediation

**Source:** `LOLM_Grand_Behavioral_Reliability_Audit.pdf` (2026-08-01)  
**Package:** `lolm.reliability`  
**Wiring:** `local_ui/code_agent.py`, CLI `last` / `retry` / `resume`

## Verdict preserved

> A hardened, truthful CLI shell around a still-fragile autonomous recovery policy.

Receipt fail-closed behavior is **not** weakened. Remediations change **state abstractions and evidence contracts**, not prompt patches or Snake-specific rules.

## Modules (audit §8.6)

| Module | Path | Responsibility |
|--------|------|----------------|
| Dynamic Contract Compiler | `lolm/reliability/contract_compiler.py` | Exact outputs, contradictions, feasibility |
| Verification Capability Graph | `lolm/reliability/capability_graph.py` | Positive/negative tool facts |
| Typed Artifact State Machine | `lolm/reliability/artifact_state.py` | Typed lifecycle + validator routing |
| Evidence-Gated Controller Arbiter | `lolm/reliability/arbiter.py` | One binding action from all votes |
| Semantic Failure Ledger | `lolm/reliability/failure_ledger.py` | Causal fingerprints |
| Counterfactual Branch Portfolio | `lolm/reliability/branch_portfolio.py` | Strategy diversity + hard feasibility |
| Last-Known-Green Store | `lolm/reliability/checkpoint_store.py` | Immutable green snapshots / rollback |
| Artifact Closure Protocol | `lolm/reliability/closure.py` | Deterministic finalize |
| Session Intent Ledger | `lolm/reliability/session_ledger.py` | Cross-command referents |
| Retrieval Bankruptcy | `lolm/reliability/retrieval_bankruptcy.py` | No identical zero-result loops |
| Confidence bundle | `lolm/reliability/confidence.py` | Decomposed metrics (F-08) |
| Runtime manifest | `lolm/reliability/runtime_manifest.py` | Grounded self-description |
| Evidence progress budget | `lolm/reliability/progress_budget.py` | Freeze on non-positive deltas |
| Evaluation plane | `lolm/reliability/evaluation_plane/` | Queued campaigns, no quota→model-fail |
| Run glue | `lolm/reliability/run_state.py` | Per-run bundle for CodeAgent |

## Live CodeAgent wiring

1. **Open** `RunReliabilityState` at `run()` start (contract compile + capability probe).
2. **System prompt** includes binding contract + negative capabilities.
3. **Writes** blocked after ACP closure; artifacts typed on write.
4. **RUN** gated by VCG (`xdg-open` once then blocked → `html.render`).
5. **Observe** → SFL + capability facts; **LGTS** snapshot on green; rollback on syntax regression.
6. **ACP** closes PDF/exact deliverables without further model turns.
7. **EGCA** after NFET tick: hard branch / capability vetoes soft verify.
8. **Confidence** shown as *policy action certainty*, not artifact correctness.
9. **Receipt** embeds `reliability` blob + exact-count fail-closed.
10. **Session ledger** records run for `lolm last` / `retry` / `resume`.

## CLI

```bash
lolm last
lolm retry          # shows referent; confirm with --yes
lolm retry --yes
lolm resume --yes
```

Session files: `$LOLM_SESSION_DIR` or `~/.lolm/sessions/`.

## Tests

```bash
pytest tests/test_reliability_architecture.py -q
```

Maps to Appendix D scenarios D-01…D-10 plus structural gates (typing, SFL merge, branch diversity, budget freeze, EGCA determinism).

## What is intentionally not claimed

- Hosted Evaluation Plane is **in-process queue scaffolding** until authenticated campaign endpoints ship on the public service.
- Full 10k gauntlets from §9 are release gates, not this PR's CI suite.
- Model quality is unchanged; controller evidence binding is the target.


## Invariant hardening (post independent review)

Addressed before re-review:

1. Closure hashes actual file bytes; claimed hashes must match; invalid PDF magic fails closed.
2. PDF force-override removed entirely.
3. Exit code 0 preserved (`coerce_exit_code` — never `x or 1`).
4. HTML verifier accepts `working`/`renders` schema from code_routes.
5. LGTS green requires typed meaningful validators (not `cat`).
6. Regression detects contract/verifier/semantic drops, not only compile.
7. Exact-tree restore deletes extras (`sandbox.delete_file`).
8. Session IDs sanitized/hashed against path traversal.
9. Resume package transports workspace + checkpoint + failure ledger.
10. CLI persists hosted `session_ledger` events into `~/.lolm/sessions`.
11. Evidence progress budget fed from the live loop.

Independent tests: `tests/test_reliability_invariants.py`.


## Coding-loop language routing (Snake retest)

Product-level failures from the hosted snake run are addressed structurally:

1. **Artifact language routing** (`code_loop_guard.py`): HTML body in `.py` is refused for `py_compile` and redirected to `index.html`. HTML-primary tasks block new Python app files.
2. **Permanent capability blocks**: `desktop.open` is marked definitive-negative at run start; repeated `xdg-open` never re-executes; alternates route to `html.render`.
3. **Binding branch**: EGCA `BRANCH_WITH_CONSTRAINTS` sets `force_branch`, clears verify debt, accepts a non-Python strategy vector, and injects a binding format nudge (index.html only).
4. **Feasibility preflight**: verifier plan chosen before mutation; desktop open never an acceptance criterion.
5. **Repair race**: run-failed candidates cannot win as progress (`repair_candidate_acceptable`).
6. **Early stop**: semantic root-cause recurrence + empty branches + capability infeasibility restore LGTS and finish stuck.
7. **HTML write-time verify**: `html.render`/static lint on write; green snapshots preserved.

Retest:

```bash
lolm code "Build a complete playable Snake game as a single index.html file. ..." \
  --save ./snake-game --max-steps 12 --idle-timeout 120000 --timeout 300000 \
  --receipt ./snake-game.receipt.json
```
