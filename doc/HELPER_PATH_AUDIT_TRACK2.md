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

## Track 3 boundary

- Passive telemetry may start **after** Phase A pass (label from verifier/repo evidence only).
- **Do not** enable adaptive/learned routing until Phase B (≥120 organic runs) passes, Track 1 has real-traffic factuality outcomes, and failed/stuck/rolled-back outcomes are retained.
