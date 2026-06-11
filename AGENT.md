# The NFET Agent — control from latent dynamics

This document describes the agent layer of LOLM-NFET: an agent whose control
decisions come from **measured internal dynamics of a neural network**, not
from prompted self-reports.

## The idea

Every token the local model generates, the LOLM-NFET graft measures four
observables of the trajectory:

| Observable | Meaning |
|---|---|
| **logit entropy** | how uncertain the next-token distribution is |
| **hidden drift** | how fast the corrected hidden state is moving (lag-1, across streamed tokens) |
| **gate mean** | the surface-vs-latent balance of the fused representation |
| **regime entropy** | how spread the discrete regime detector is |

The `NFETController` head maps `[hidden, entropy, drift, gate, regime]` to
five control actions:

```
0 continue   keep generating
1 retrieve   go get evidence (memory, optionally web)
2 verify     check the draft against the evidence
3 branch     fork alternatives, keep the healthiest
4 finalize   wrap up and answer
```

Prompted agents *ask the model* whether it is uncertain. This agent
*measures* it.

## The loop (`local_ui/nfet_agent.py`)

```
command ──► generate segment ──► policy.decide(telemetry, head logits)
                 ▲                    │
                 │      continue ─────┤
                 │      retrieve ─────┼─► memory/web evidence injected
                 │      verify ───────┼─► verifier pass; critique fed back
                 │      branch ───────┼─► K continuations, healthiest kept
                 │                    │
                 └────────────────────┘
                        finalize ────► polished answer + proof receipt
```

Decisions are made at segment boundaries by `lolm/nfet_policy.py`:

- **Calibrated heuristic** — rolling z-scores of each observable against the
  run's own history (snapshot baselines, std floors, sustain windows,
  cooldowns). Works with an untrained head from the first run.
- **Trained head override** — when a controller checkpoint is loaded
  (`head_trained: true`), a confident head takes the decision instead,
  decision by decision. Every decision records its `source`
  (`heuristic` / `head` / `budget` / `cooldown`).

Budgets (`max_retrieves`, `max_verifies`, `max_branches`, `max_segments`)
bound every run. Every run ends with a **proof receipt**: the same command run
in plain base mode, compared against the agent's answer, with the control
timeline summarized — the workspace's honest-by-construction habit.

## The flywheel (`scripts/train_nfet_controller.py`)

Every chat and agent run logs per-token telemetry to the improvement log.
The trainer turns that traffic into supervision for the control head:

1. **Bootstrap** (no model needed): distill the calibrated heuristic into the
   head from synthetic scenarios and/or real logged observables. Hidden-state
   columns are zeroed — the bootstrapped head is exactly an
   observable-driven policy in network form.
   ```bash
   make nfet-controller          # synthetic bootstrap -> runs/nfet_controller/ckpt.pt
   ```
2. **Replay** (full fidelity): re-run logged text through the frozen backbone
   + graft and train on real hidden states — where the head can learn
   signals the heuristic cannot see.
   ```bash
   PYTHONPATH=. python scripts/train_nfet_controller.py \
       --replay local_ui/data/improvement_log.jsonl --profile qwen3_0_6b_smoke
   ```

Load the checkpoint via the model loader's graft-checkpoint field (or
`--ckpt` on the smoke script); the workspace flips `head_trained` on and the
head starts taking over.

So the loop closes: **use the agent → log telemetry+decisions → train the
head → the head drives the agent better → repeat.**

## Frontier mode: Claude as the voice, LOLM as the monitor

`local_ui/claude_reasoner.py` implements the same generation-loop event
protocol as the local model, backed by the Claude API (`claude-opus-4-8` by
default, official `anthropic` SDK). The local graft **re-reads Claude's
output** through the frozen backbone and produces full NFET telemetry for it
— entropy, drift, gate, regime, control logits per token.

That means the same control loop runs with a frontier brain: Claude writes,
the local latent machinery watches and decides when to retrieve, verify,
branch, or stop.

```bash
pip install -r requirements-agent.txt   # adds anthropic + mcp
export ANTHROPIC_API_KEY=...            # or `ant auth login`
# then: POST /api/agent/nfet/run {"command": "...", "reasoner": "claude"}
PYTHONPATH=. python scripts/smoke_nfet_agent.py --reasoner claude
```

Without a local model loaded, frontier mode still answers (control degrades
to budget-driven continue); load the local model to give Claude the monitor.

## Open platform: the MCP server

`local_ui/mcp_server.py` exposes the whole workspace over the Model Context
Protocol — Claude Code, Claude Desktop, or any MCP client can use:

| Tool | What it does |
|---|---|
| `load_local_model` / `workspace_status` | arm and inspect the local model |
| `lolm_chat` | chat with live NFET telemetry |
| `nfet_agent_run` | the full control loop (local or claude reasoner) |
| `memory_search` / `memory_add_note` / `memory_recent` | persistent local memory |
| `identity_get` / `identity_add_line`, `goals_list` / `goals_add` | durable identity and goals |
| `journal_read` / `journal_write` | the running journal |
| `improvement_log_tail` | the flywheel data |

The repo ships a ready `.mcp.json` — open this repo in Claude Code and the
`lolm-nfet` server is available immediately.

## HTTP API

`python local_ui/server_agent.py` serves everything:

| Route | What |
|---|---|
| `POST /api/agent/nfet/run` | the NFET-controlled agent (this document) |
| `GET /api/agent/nfet/last` | last run with full timeline |
| `POST /api/agent/run` | the fixed-pipeline orchestrator (predecessor) |
| `POST /api/command/run`, `/api/self/tick`, `/api/proof/compare` | command center, self-tick, proof mode |
| `POST /api/chat`, `/api/chat/stream` | chat with per-token NFET telemetry |

## Quick start

```bash
pip install -r requirements-agent.txt

# offline tests (no model download)
make nfet-tests

# bootstrap the controller (CPU, ~1 min)
make nfet-controller

# end-to-end on the real local model (downloads Qwen3-0.6B)
make nfet-smoke
```

## Files

```
lolm/nfet_policy.py              # calibrated control policy + weak labeler
lolm/nfet_controller_train.py    # control-head training (bootstrap + replay)
lolm/nfet_graft.py               # graft; NFETController head; drift override
local_ui/nfet_agent.py           # the control loop with real action dispatch
local_ui/claude_reasoner.py      # frontier voice, local monitor
local_ui/mcp_server.py           # the workspace as an MCP server
scripts/train_nfet_controller.py # flywheel trainer CLI
scripts/smoke_nfet_agent.py      # end-to-end smoke
tests/test_nfet_*.py, tests/test_claude_reasoner.py, tests/test_mcp_server.py
```

## The public demo (lolm.imagineqira.com)

The agent runs live at [lolm.imagineqira.com](https://lolm.imagineqira.com):
`local_ui/server_public_demo.py` binds the workspace to localhost on the web
box; nginx forwards only `/api/demo/` (everything else stays loopback-only).
`local_ui/public_demo.py` clamps budgets, enforces one run at a time, and
rate-limits per visitor — sized for a shared 2-vCPU host. The page plays a
library of recorded real runs (`make demo-replays`) instantly and streams live
runs over SSE (`/api/agent/nfet/run/stream` is the same protocol locally).

The controller checkpoint serving the demo was bootstrapped from synthetic
scenarios, then retrained on the workspace's own logged traffic
(`--log improvement_log.jsonl`) — the first turn of the flywheel. Decision
sources are visible in every timeline: `head` where it is confident,
`heuristic` where it is not, `budget` where limits intervened.

## Scaling the backbone

The machinery is backbone-agnostic: the graft attaches to any Hugging Face
causal LM. The 4B pipeline, end to end on a Mac (M-series, 24GB):

```bash
# 1. graft (token-loss path) — ~15 min on MPS, streams FineWeb-Edu
PYTHONPATH=. python scripts/train_hf_graft_stream.py \
  --profile qwen3_4b_lab --device mps --latent-backend gru_debug \
  --steps 300 --seq-len 256 --out runs/hf_graft_4b/graft.pt

# 2. control head (observables + your logged traffic + outcome labels) — ~2 min CPU
PYTHONPATH=. python scripts/train_nfet_controller.py \
  --log local_ui/data/improvement_log.jsonl --outcomes local_ui/data/improvement_log.jsonl \
  --synthetic 150 --d-model 2560 --latent-backend gru_debug \
  --checkpoint-in runs/hf_graft_4b/graft.pt --out runs/nfet_controller/live_qwen4b.pt

# 3. run it
PYTHONPATH=. python scripts/smoke_nfet_agent.py --profile qwen3_4b_lab \
  --device mps --ckpt runs/nfet_controller/live_qwen4b.pt
```

The same controller training rides on top regardless of scale because the
policy operates on observables, not on the backbone's width.

## Bring your own notes

```bash
make import-notes NOTES=~/your/markdown-folder   # heading-aware, idempotent, local
make agent-ui                                    # retrieval now hits YOUR facts
```

Retrieval ranks by relevance x importance over the whole store; recency is a
tiebreak, never a reason to inject something off-topic.
