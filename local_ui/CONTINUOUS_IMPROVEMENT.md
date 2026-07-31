# Continuous improvement log

## 2026-07-30 night — resume after Claude usage limit (Grok)

### Diagnosis (honest remeasure of ensemble)
- Ensemble arm had hit **76.7%** pass / **10%** overclaim (n=60).
- Honesty-guard remeasure finished at **65%** pass / **18.3%** overclaim.
- Dominant failure modes:
  1. **Protocol bleed** — models paste `RUN: python3 …` *inside* the FILE fence → `SyntaxError`, 22-step thrash (roman, expr_eval, semver, jsonpath).
  2. **Overclaim on incomplete self-tests** — green happy-path prints, then DONE, while TASK reject cases (`''`, malformed, multiline CSV) still fail.
  3. Auto-finish oracle treated the word **"hello"** (as a reject example) as a "hello world" task and finished early.

### Shipped fixes
- Strip FILE/RUN/DONE/READ/EDIT lines out of code fences at parse + write; auto-strip on py_compile fail.
- Ensemble scorer zeros candidates with protocol bleed in the *raw* fence (before sanitize).
- **Contract probe** before DONE (and before auto-finish): runs the TASK's own `'x' -> y` examples and raise-ValueError literals against the delivered module.
- Tightened clean-run auto-finish keywords so reject-case words cannot short-circuit.
- Root `package.json`: `npm run help` / `lolm` / `lolm:status` so private ops scripts stop looking like a dead CLI.

### Still open (next loop)
1. Re-bench n=60 on prod after deploy — target ≥ ensemble 76.7% with overclaim ≤ 10%.
2. Hard tasks still soft: `fix_csv_parser` (multiline + doubled quotes), `jsonpath` negatives, `expr_eval`.
3. Embedding-backed memory; visual builder verify+retry.

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

## 2026-07-26 loop — code receipts + expected-output gate + static visual lint
### Agentic coding (win #1)
- Every code run ends with a sealed **`code_receipt`** (trail, sha, green/fail runs, verifies)
- DONE blocked when task named concrete outputs (e.g. print 42) that never appear in stdout
### Receipts (win #4)
- Workspace receipt pane shows code action trail + receipt sha (reason to switch vs black box)
### Visual builder
- When Playwright missing: **static HTML lint** rejects blank canvases so auto-retry still fires
- Clear reasons in verdict (`static lint: …`) — never silent ship of dead UI
### Next queue
1. Real embedding index for memory
2. Between-turn operator ticks on local operator mode
3. Persist code_receipts.jsonl ledger server-side
4. npm client: surface code_receipt event type

## 2026-07-26 loop — code receipt ledger + npm + continuity ticks
### Receipts / auditability (win #4)
- Server-side **hash-chained** `code_receipts.jsonl` ledger on every `/api/demo/code/run`
- Public `GET /api/demo/code/receipts` audit window + health embeds ledger stats
### Findability / npm (win #6)
- `lolm-nfet-client@0.2.1`: `onCodeReceipt`, `listCodeReceipts`, friendly narration for code events
- why-switch: code receipt ledger called out vs Claude/Codex
### Continuity (win #2)
- `continuity_tick.between_turn` after dialog turns (summary + promote + pack, zero tokens)
### Agentic coding (win #1)
- DONE blocked when multi-file imports reference sibling modules never written
### Next queue
1. Real embedding index for memory
2. Richer between-turn operator ticks (model-backed, local-only)
3. Publish npm 0.2.1 to registry
4. Persist visual-build receipts similarly

## 2026-07-26 loop — TF-IDF memory, visual receipts, import auto-coach
### Continuity / memory (win #2)
- Memory search: **TF-IDF cosine** over note corpus + n-grams (embedding substitute, no deps)
### Receipts (win #4)
- Visual builds seal **visual_receipt** into the same hash-chained ledger (html_sha, verified, attempts)
### Agentic coding (win #1)
- ModuleNotFoundError auto-coaches: write missing `FILE: mod.py` before DONE
### Findability (win #6)
- llms.txt: why-switch + code receipts API; npm client narrates visual_receipt (0.2.2)
### Next queue
1. Optional ONNX/local real embeddings when available
2. Model-backed between-turn operator ticks (local-only)
3. npm publish 0.2.2
4. Public mini /receipts.html audit page

## 2026-07-26 loop — public receipts page + syntax auto-coach
### Receipts / findability (wins #4 #6)
- **`/receipts.html`** live audit UI over `/api/demo/code/receipts` (filter code/visual/ok)
- Sitemap + llms.txt + why-switch + pricing nav link the ledger
- API slim rows include `kind`, `attempts`, `html_sha`
### Agentic coding (win #1)
- SyntaxError / IndentationError / NameError auto-coach surgical EDIT/FILE fix
### Next queue
1. Optional ONNX embeddings
2. Model-backed between-turn ticks (local)
3. npm publish
4. Seed demo receipts on deploy for empty-ledger UX (optional)

## 2026-07-26 loop — continuity in memory path + demo receipt seeds
### Continuity (win #2)
- Short **dialog** follow-ups pull identity + rolling summaries into memory_hits
- Finalizer injects CONTINUITY pack (identity/thread) every turn
- continuity_tick can **read pack without writing** (between-turn hygiene)
### Receipts / findability (wins #4 #6)
- Empty ledger auto-seeds **labeled demo** receipts so /receipts.html shows format
- Workspace nav: Why switch + Receipts
### Agentic coding (win #1)
- AssertionError auto-coach before DONE
### Next queue
1. ONNX embeddings optional
2. Model-backed local ticks
3. npm publish
4. Real live code run to fill non-demo ledger

## 2026-07-26 loop — auto-DONE oracle + speed starters
### Agentic coding + speed (wins #1 #3)
- **Auto-DONE** when expected stdout or tests are green (no extra model turn)
- Workspace empty-state starters emphasize coding, memory, why-switch, receipts links
### Next queue
1. ONNX embeddings optional
2. Model-backed local ticks
3. npm publish
4. Capture real non-demo ledger runs from public traffic

## 2026-07-26 loop — py_compile preflight + try discovery
### Agentic coding + speed (wins #1 #3)
- **py_compile preflight** after every .py write/edit before RUN (catch syntax early)
- Timeout/kill auto-coach for infinite loops
- Simple print tasks cap at 10 steps
### Continuity (win #2)
- "do that" / "go for it" / "once more" treated as affirm
### Findability (win #6)
- try.html nav: why switch, receipts, pricing, workspace

## 2026-07-26 loop — runtime error coaches + option reject + npm ledger docs
### Agentic coding (win #1)
- FileNotFound / ZeroDivision / Index|Key|Type|ValueError auto-coaches
### Continuity (win #2)
- "not A" / "the other one" option reject/pick paths
### Findability (win #6)
- npm README: listCodeReceipts + receipts.html; package 0.2.3
- why-switch + pricing link live receipts ledger

## 2026-07-26 loop — stdlib import coach + hash embeddings + model ticks
### Agentic coding (win #1)
- **Third-party import coach**: ModuleNotFound for requests/numpy/… → rewrite with stdlib (no fake FILE: requests.py)
- AttributeError / UnboundLocalError / RecursionError / JSONDecodeError auto-coaches
### Continuity / memory (win #2)
- Memory: **feature-hashing dense embeddings** (128-d, zero deps) + TF-IDF + n-grams
- Heuristic fact extract + optional **model-backed tick** (`LOLM_MODEL_TICK=1` + generate)
- "which one?" / either / both / neither dialog continuity
### Findability (win #6)
- try.html live chip: code self-fix; why-switch memory row names hash embeddings
### Next queue
1. Wire local generate into model_backed_tick on operator boxes
2. ONNX embedder plugin slot when weights present
3. npm publish 0.2.3+
4. Real non-demo ledger traffic samples

## 2026-07-26 loop — local tick wire + embedder plugin + empty-stdout coach
### Continuity (win #2)
- `resolve_local_tick_generate`: auto evolved/local when `LOLM_MODEL_TICK` or `LOLM_OPERATOR_LOCAL`
- `nfet_agent` wires generate into `between_turn` + emits `continuity_tick` SSE event
- Dialog: "same as before" / "as I said" resume prior plan
### Memory (win #2)
- Embedder plugin slot (`set_embedder` / `LOLM_ONNX_EMBED`) with hash fallback
### Agentic coding (win #1)
- PermissionError / IsADirectoryError / NotADirectoryError path coaches
- Exit-0 empty stdout coach when task expects print (blocks auto-DONE)
### Findability / npm (win #6)
- `lolm-nfet-client@0.2.4`: friendly() for `learned` + `continuity_tick`
### Next queue
1. npm publish 0.2.4 to registry
2. Real ONNX tokenizer+session path when model weights land
3. Surface continuity_tick in workspace UI
4. Non-demo ledger samples from live traffic

## 2026-07-26 loop — continuity UI + live selftest receipt + speed hints
### Continuity / findability (wins #2 #6)
- Workspace (`index.html`) surfaces **`continuity_tick`** SSE (facts / local model / open loop)
- Dialog affirm: "pick for me" / "you decide" / "dealer's choice"
### Receipts (win #4)
- **`ensure_selftest_receipt`**: real sandbox write+run of `print(42)`, sealed non-demo
- `/api/demo/code/receipts` triggers selftest; receipts.html shows **live selftest** badge
### Agentic coding + speed (wins #1 #3)
- First-turn context injects **EXPECTED STDOUT** from task text
- Auto-retry `python` → `python3` when python missing
- UnicodeEncode/Decode + EOFError (input()) coaches
### Next queue
1. npm publish 0.2.4
2. Workspace chip for open_loop from continuity_tick
3. Real ONNX tokenizer when weights land
4. Capture organic non-selftest ledger traffic

## Train/improve loop (serious)
- scripts/train_improve_loop.py: HF ingest → queue mint → gated LoRA → promote → restart serve
- Fixed corrupt live adapter (was destroying generation; quarantined)
- Fixed empty live/ false-positive resume; daemon rotates/drops unlearnable facts
- Cycle 241 PROMOTED learn=1.0 keep=1.0 (LOLM curriculum facts)
- Scoreboard: runs/train_improve/latest.json
