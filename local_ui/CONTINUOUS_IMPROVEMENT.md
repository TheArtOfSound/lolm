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

## 2026-07-26 5m loop — usage remaining API + evolved rescue land
### Monetization (B)
- `usage_limits.usage_status()` peeks remaining runs/builds **without** consuming a unit
- `GET /api/demo/billing/usage` + richer `/api/demo/billing/config` (used/limit/remaining)
- Workspace chip: live **N/limit runs left today**, refreshes after each turn
- Pricing: live plan banner, low-budget nudge, cancel/claim UX; Stripe success→`pricing.html`
### Product (A)
- Code agent: pre-DONE **pytest/unittest oracle** when test files exist; py_compile fallback
- Memory: promote durable summary facts → `identity.md` for long-thread continuity
- Claude harness + PreToolUse gate + MCP monitor tools (tests green)
- Evolved `:11435` rescue path already live from prior loop

## 2026-07-26 loop — code oracle + identity continuity + ship
### Agentic coding (win #1)
- Code agent verify: **pytest/unittest oracle** when test files exist; py_compile for multi-file
- DONE gated on green tests when `test_*.py` / `*_test.py` present (Claude/Codex parity)
### Continuity (win #2)
- Rolling summaries can **promote durable facts → identity.md** (remember/my name/prefer/…)
- Auto-capture turns promote so later chats still resolve personal facts
### Monetization / findability
- Remaining-budget chip + pricing live plan banner (non-consuming peek API)
- Claude harness receipts + PreToolUse hook ship with the deploy
### Next queue
1. Embedding-backed memory retrieval
2. Between-turn operator ticks on local operator mode
3. Visual builder: always verify + auto-retry on blank canvas
4. JSON tool schema for code agent (strict actions)

## 2026-07-26 loop — JSON tools + soft memory + option continuity
### Agentic coding (win #1)
- Code agent accepts **JSON tool schema**: write/run/read/edit/list/finish + multi-`actions[]`
- Text **READ:** / **EDIT:** blocks for surgical fixes without full rewrites
- Edit applies unique old→new replace; auto-RUN after write/edit still on
### Continuity (win #2)
- Option picks (`A`/`B`/`the second one`) resolve against last assistant choices
- Memory retrieval: char-trigram soft match + identity paraphrases (mini-embedding, no deps)
### Speed / findability
- try.html **live starter chips** (receipt / why switch / memory) fire real agent turns
- why-switch: agentic row upgraded to multi-file + JSON tools + test oracle
### Next queue
1. Real embedding index for memory (optional ONNX/local)
2. Between-turn operator ticks on local operator mode
3. Visual builder: force verify path even when playwright missing reports clearer
4. Surface code-agent receipt trail more prominently in workspace UI
