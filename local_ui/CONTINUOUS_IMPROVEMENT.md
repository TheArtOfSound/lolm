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
- Evolved local :11435 auto-discover + rescue after Claude/Workers fail mid-dialog

## Deploy
  DEPLOY_SSH_HOST=autohustle-aws bash deploy/deploy_box.sh

## Next queue (do not wait for user)
1. Embedding-backed memory retrieval
2. Code agent: JSON tool schema + pytest oracle
3. Between-turn operator ticks on local operator mode
4. Visual builder: always verify + auto-retry on blank canvas
5. Persist conversation summaries into identity.md for long-term continuity

## Ultimate goal
Be a better default daily agent than Claude Code / Codex for people willing to switch:
- Agentic coding that runs + fixes in a real jail
- Conversation that doesn't break on short replies
- Receipts + memory + fair price + optional local
- Continuous deploy until quality is felt

## Competitive wave (live)
- Code agent: multi-file FILE blocks, 18–22 steps, py_compile verify, history-aware tasks
- /why-switch.html comparison page
- Pricing + try funnel + share still live
