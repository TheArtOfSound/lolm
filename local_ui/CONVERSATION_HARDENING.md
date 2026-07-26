# Conversation hardening (2026-07-26)

## Problem
LOLM felt like a toy because every turn was a cold `COMMAND`:
- "idk" → dictionary definition
- "yes"/"no" → no thread continuity
- always-on web search polluted short follow-ups
- history was a flat string dump, not multi-turn chat
- local `max_new_tokens=96` truncated answers
- knowledge queue only filled in sovereign mode

## Fixes shipped
1. `local_ui/conversation.py` — dialog classification, short-reply resolution, web gating, multi-turn message builder
2. `nfet_agent.py` — history-aware profiles (`social|dialog|question|task`); dialog/social skip multi-segment theater; finalize uses real chat messages
3. `public_demo.py` — skip web search on short/social/dialog turns
4. `site/index.html` — client-side history kept live; short replies forced to chat route
5. `server.py` — default `max_new_tokens` 96 → 768
6. `workspace_routes.py` — knowledge queue fills when `LOLM_OPERATOR_LOCAL` / `LOLM_LEARN_ALWAYS`

## Smoke
```
idk + history about conversation vs coding
→ profile=dialog followup=unknown
→ "No problem. Let's focus on the conversation first..."
→ DEFINES_SLANG=false ON_TOPIC=true
```

## Still open (next)
- Coding agent: structured tools + higher step budget + tests as oracle
- Embedding memory retrieval (not just bag-of-words)
- Wire local evolved serve (11435) as default GEN when Claude/Workers unavailable
- True between-turn operator ticks on local (L3+)
