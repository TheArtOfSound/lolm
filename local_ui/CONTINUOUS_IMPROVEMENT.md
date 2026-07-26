# Continuous improvement log

## Live now (https://lolm.imagineqira.com)
- Dialog intelligence: idk/yes/no follow-ups (no dictionary nonsense)
- Web search gated off for short/social/dialog turns
- Multi-turn finalize messages
- Local max_new_tokens 768
- Knowledge queue on LOLM_OPERATOR_LOCAL
- Coding agent: 14 steps, format re-prompt, auto-RUN
- Memory short-token retrieval
- Capture learning from raw user text

## Deploy
  DEPLOY_SSH_HOST=autohustle-aws bash deploy/deploy_box.sh

## Next queue (do not wait for user)
1. Embedding-backed memory retrieval
2. Code agent: JSON tool schema + pytest oracle
3. Prefer evolved local serve (11435) when Claude/Workers fail mid-dialog
4. Between-turn operator ticks on local operator mode
5. Visual builder: always verify + auto-retry on blank canvas
6. Persist conversation summaries into identity.md for long-term continuity
