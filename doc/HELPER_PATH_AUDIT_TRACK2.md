# Helper-path audit — Track 2 (organic repository gauntlet)

Status: Phase A qualification passed (`qualification_passed: true`).  
Track 3 adaptive routing: **not enabled**. Passive telemetry only after Phase A; learned routing deferred until Phase B + Track 1 real-traffic gates.

## Rule

Every **active-repository** mutation must pass through `MutationGateway` (read-before-edit + CAS + receipt).  
Scratch scoring sandboxes may write directly only when isolated and never promoted without a fresh RBE/CAS cycle.

## Product CodeAgent path (`local_ui/code_agent.py`)

| Path | Status |
|------|--------|
| FILE / full rewrite | `_gateway_write` → gateway |
| EDIT surgical | `_gateway_write` (no fallback `sb.write_file`) |
| Auto-strip protocol bleed | explicit `gw.read` then `_gateway_write` |
| Repair-race promotion | fresh `gw.read` when exists, then `_gateway_write` |
| Contract probe write on active tree | `_gateway_write(..., creating=True)` |
| Scratch candidate scoring | `Sandbox(self.sb.root)` → new session dir; `reason="candidate"`; **not** active tree |
| Gateway unavailable | `PermissionError` (no unguarded fallback) |

## Surfaces that are **not** the CodeAgent product path

These may still call `Sandbox.write_file` directly. They are **out of band** for Track 2 CodeAgent qualification and must not be used as a silent bypass for agent proposals:

| Surface | Role | Policy |
|---------|------|--------|
| `local_ui/agent_operator.py` | Human/operator loop | Operator-initiated; not CodeAgent proposal |
| `local_ui/sandbox_routes.py` | HTTP sandbox API | Authenticated API; not agent loop |
| `lolm/reliability/checkpoint_store.py` (LGTS) | Explicit restore | Restore path, not proposal |
| `lolm/reliability/run_state.py` resume | Checkpoint materialize | Restore path |
| Gauntlet seed | `_seed_repo` / `reason="gauntlet_seed"` | Fixture only |
| `local_ui/code_receipts.py` tests | Unit/fixture | Test only |
| MCP tool surface | Documented action vocabulary | Must not open a second write channel into active agent runs without gateway |

## Mutation primitives search (active repo risk)

Searched for: `write_file`, `delete_file`, `rename`, `replace`, `apply_patch`, `open(..., "w")`, `Path.write_text`, `shutil.move`, `mv`, `rm`, `sed -i`, `perl -pi`, `cat >`, `echo >`, `tee`, `git apply`, `patch`.

**CodeAgent active-tree writes** go through gateway only (after Phase A RBE fix: no auto-read, no unguarded fallback).

Shell-based mutation via `RUN:` remains possible if the model issues `sed`/`mv` etc. That is a **verifier/policy** concern for Phase B (command preflight / denylist expansion), not a silent Python API bypass. Phase A scripts do not exercise shell mutation.

## Scratch sandbox isolation

`Sandbox(root)` creates `root / session_id` — scoring sandboxes share the **parent root**, not the **active session dir**. Candidate content is not the active repository. Promotion into the active tree must use `_gateway_write` with a new read authorization (repair-race path does this).

## Phase A organic zero-counts (required)

```
Blind existing-file mutations applied = 0
Stale-revision mutations applied = 0
Receipt/filesystem mismatches = 0
Trust aborts = 0
qualification_passed = true (20/20)
```

## Out-of-band disposition (trust classes)

| Surface | Trust class | Policy |
|---------|-------------|--------|
| CodeAgent FILE/EDIT | `code_agent_gateway` | RBE + CAS + gateway receipts |
| Operator write/edit | `privileged_operator` | Capability surface + privileged receipt + pre/post tree hash |
| Sandbox HTTP API write | `privileged_http_sandbox` | Bearer token + privileged receipt (not CodeAgent) |
| Public demo sandbox write | `privileged_http_sandbox` | Isolated demo; privileged receipt; `public_demo` flag |
| LGTS materialize | `recovery_lgts` | Typed `restore_checkpoint` transaction; **no** edit auth grant |
| Resume package apply | `recovery_resume` | Typed recovery transaction; **no** edit auth grant |
| Gauntlet seed | `gauntlet_seed` | Fixture only |

Recovery privileges cannot be reused for subsequent ordinary edits
(`grants_edit_authorization: false` on all recovery transactions).

Implementation: `lolm/privileged_mutation.py`.

## Track 3 boundary

- **Passive shadow telemetry: ON** (`lolm/shadow_telemetry.py`, wired via
  `AgentCapabilityCore.prepare_request` + CodeAgent/NFET outcome recording).
- Shadow may recommend planner/executor/verifier; **must not** alter live
  selection (`ADAPTIVE_ROUTING_ENABLED = False`).
- Adaptive routing stays blocked until Track 1 real-traffic factuality,
  Track 2B live-model gauntlet, per-bucket ≥30 observations, and shadow
  outperformance gates pass.
- Failed/stuck/rolled-back/timed-out/abstained outcomes are retained.

## Track 2 split

| Layer | Status |
|-------|--------|
| Track 2A mutation integrity (scripted organic A+B) | **Passed** at `84a4bc5` |
| Track 2B open-ended live-model competence | **Unproven** — harness: `scripts/repo_gauntlet_live_model_phase_a.py` |
