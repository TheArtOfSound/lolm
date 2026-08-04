# LOLM Evolution Plane

**Goal:** Did the new weights measurably improve real LOLM tasks without forgetting old skills or weakening safety?

## Status: production spine (live)

| Piece | Status |
|-------|--------|
| Receipt dual-write from `code_receipts.append` | Live |
| Bronze → Silver → Gold | Live |
| SFT + preference-as-SFT + teacher distill | Live |
| Real MLX LoRA train (Qwen2.5-3B) | Live when mlx-lm installed |
| Four promotion gates + shadow | Live |
| Canary promote + advance (5→25→50→100) | Live |
| `serve_evolved` prefers `runs/evolution/live` + canary | Live |
| Volatile pricing/URLs → retrieval only | Live (`runs/retrieval_facts.jsonl`) |
| launchd install | `scripts/install_evolution_agent.sh` |

## Layout

```text
lolm/evolution/          # library
scripts/evolution_*.py   # CLI
scripts/serve_evolved.py # canary-aware serve
runs/evolution/
  raw/ silver/ gold/
  datasets/ candidates/
  live/ previous/
  receipts/ registry.jsonl
```

## Commands

```bash
# Full cycle (auto real-train if mlx present)
PYTHONPATH=. python scripts/evolution_daemon.py --once --force --canary 0.05

# Force dry-run (CI)
PYTHONPATH=. python scripts/evolution_daemon.py --once --force --dry-run

# Install always-on agents (serve + evolution daemon)
bash scripts/install_evolution_agent.sh

# Point brain at evolved weights
export LOLM_LOCAL_API=openai
export LOLM_LOCAL_URL=http://127.0.0.1:11435
export LOLM_LOCAL_MODEL=lolm-evolved
```

## What trains vs retrieval

| Weights (skills/policies) | Retrieval / config only |
|---------------------------|-------------------------|
| read-before-edit, tools   | pricing, quotas, URLs   |
| recovery, rollback        | model availability      |
| verify, no false DONE     | customer-specific facts |
| abstain, file selection   | news / laws / docs ver  |

## Promotion path

```text
train candidate → Gate1 integrity → Gate2 frozen skills
  → Gate3 real LOLM probes → Gate4 shadow
  → canary 5% → 25% → 50% → 100%
  → previous_known_good always retained
```

Dry-run stubs never receive production canary traffic (`serve_evolved` skips them).

## Integration

- **`train_improve_loop.py`** runs evolution first, then skill fact LoRA (volatile filtered).
- **`code_receipts.append`** dual-writes full trail trajectories to `runs/evolution/raw/`.
- **`install_life_agents.sh`** installs evolution + serve + optional knowledge daemon.
