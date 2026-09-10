# Changelog

## 2.3.0 - 2026-09-10

The agent can delegate, read in parallel, and survive a provider refusing a
tool call.

- **`agent.delegate`** hands one self-contained question to a fresh agent with
  no history, which returns only its conclusion plus a receipt of what it
  changed. The point is context, not concurrency: a thirty-file search no longer
  lives in the caller's history for the rest of the task. A delegate cannot see
  the calling conversation and cannot delegate further; six per run. It runs
  without the controller — it is a lookup, not a trajectory worth steering — and
  delegating never counts as evidence;
- **independent reads in one turn run together** and cost one step instead of
  one step per file. Only confirmation-free reads qualify; anything that writes,
  executes, or could prompt stays strictly in order, so a write followed by a
  patch of the same file still sees what the write produced;
- **a provider that refuses a tool call is no longer fatal.** Groq validates
  tool calls server-side and answers `tool_use_failed` when the model gets a
  schema wrong, or `output_parse_failed` when it cannot parse the generation —
  both used to end the task outright. The model is now told what was refused and
  gets at most two corrections before the real error surfaces. A throttle, a
  missing key, or a 400 without tool wording is never mistaken for a correctable
  mistake.

Verified hermetically: seven tests drive the real agent loop and the real HTTP
transport against localhost servers, asserting that a delegate starts with an
empty history and never leaks the caller's request, that two reads in one turn
produce two results in the right order for one step, that a write-bearing turn
is never batched, and that a rejection recovers once but does not loop. A live
end-to-end check was not possible today: Gemini's free tier returns 404 across
every model, Cerebras returns 402, OpenRouter's 50 free requests are spent, and
Groq's 8,000 tokens-per-minute cannot fit a single tool-using agent request.

## 2.2.0 - 2026-09-10

The agent knows it has a budget.

- the step budget is stated in the system context, and the agent is told to
  issue independent tool calls together rather than one per turn and to give its
  final answer once verification has actually passed instead of polishing. Two
  steps from the cap it is warned once, carried into that step rather than
  spending a turn on the warning. This came from reading benchmark traces: eight
  of twelve runs spent the whole budget, one wrote the same file five times, and
  another ran a passing test and then patched the file again. **The effect on
  step counts is not yet measured** — every hosted tier was unavailable the day
  it shipped — and `BENCHMARK_EVIDENCE.md` says so rather than claiming a win;
- benchmark honesty, two fixes. An HTTP 503 was scored as a model failure: the
  infrastructure classifier matched `429` but never `503`, and a transient
  upstream outage is now named `provider_unavailable` rather than folded into
  `usage_limit`, since a provider having a bad minute is not a user running out
  of allowance. And a run whose hidden grader passed now always counts, whatever
  noise its receipt carries — exclusion is for runs that never reached a model,
  not for successful ones.

A 2.1.0 regression check over twelve tasks scored five and passed five, with no
regressions; the other seven were the outage and the spent allowance above.

## 2.1.0 - 2026-09-10

The agent remembers, Gemini streams, and the console stops repeating itself.

- **memory across sessions** — `memory.save` / `memory.recall` / `memory.get` /
  `memory.list` / `memory.forget`, stored as one Markdown note per fact under
  `~/.lolm/memory`. The index rides in the system prompt; bodies are fetched on
  demand. `lolm memory [list|show NAME|forget NAME]` manages the store by hand.
  Saving needs no confirmation (it is the agent's own store, not the workspace);
  forgetting does. Recalling a note never counts as evidence. `LOLM_MEMORY=0`
  keeps the store out of a run and is set for every benchmark run;
- **Gemini streams** through the same server-sent-event reader as the
  OpenAI-compatible providers, keeping thought signatures for replay and
  routing thought parts to the "reasoning" status rather than the transcript;
- the "Local NFET quality controller ready" line is announced once per session,
  and the controller's other status messages are shown as themselves instead of
  being relabelled "ready" — which was why the line appeared twice.

## 2.0.0 - 2026-09-10

The agent streams, stops, plans, shows its edits, and survives long tasks.

- **streaming** — replies reach the transcript as the model writes them. The
  OpenAI-compatible path (Cerebras, Groq, OpenRouter, OpenAI, custom endpoints)
  now reads server-sent events, assembling fragmented tool-call arguments before
  parsing them; a provider that ignores `stream: true` is detected by its content
  type and served through the plain path. `--no-stream` opts out;
- **stopping** — `esc` or `^C` during a task aborts the in-flight request and
  the loop cleanly. The result is reported as a stop, not a failure, with the
  files changed and commands run before it kept and counted; `SIGINT` does the
  same without a console. An abort signal is threaded through every provider
  adapter, including backoff sleeps;
- **plans** — `plan.set` / `plan.done` / `plan.get` tools; the console pins the
  checklist under the header and ticks steps off live. Declaring a plan never
  counts as evidence toward verification;
- **diffs** — `fs.write` and `fs.patch` report a unified diff of the change they
  made, shown coloured under the tool line. It is stripped before the tool
  result re-enters the model's context;
- **context compaction** — past `LOLM_CONTEXT_CHARS` (160k) old tool output is
  trimmed; if still over budget, the middle of the conversation is compressed by
  the model into a summary and the loop continues. The system message, original
  request, and recent turns are untouched, and tool-call/result pairs are never
  split. Each compaction is reported;
- the linear console deliberately does not stream token by token: it is the
  path a screen reader hears, and the finished reply reads better than a trickle.
- a plan the model declares and then abandons earns one reminder to tick or
  finish its steps before the answer stands; it is never counted as an NFET
  intervention;
- a bare Escape no longer both stops a task *and* drops the reader into
  scrollback — readline echoes the same key about half a second later, and that
  echo is now ignored; the redundant "started" row per tool call is gone, and a
  stopped task clears its spinner and notice.

## 1.9.0 - 2026-08-12

Clipboard routing, vim scrollback navigation, and a settings panel.

- `y` in scrollback copies what is on screen through OSC 52, so it reaches the
  clipboard of the terminal you are sitting at even over SSH or from inside a
  container. It is DCS-wrapped for tmux and chunked for screen, falls back to
  `tmux load-buffer` when tmux passthrough is off, and prefers a native tool when
  LOLM is local. OSC 52 delivery cannot be confirmed by design, so every copy is
  also written to `~/.lolm/clipboard.txt` and the console reports which routes it
  used rather than claiming success it cannot verify;
- `esc` (or `^G`) enters scrollback navigation with vim's keys: `j`/`k`,
  `^D`/`^U`, `^F`/`^B`, `gg`, `G`, `/` to search, `n` for the next match. The
  viewport reports how many lines are hidden below;
- `^S` opens a settings panel over the transcript for provider, model,
  permissions, workspace, and NFET detail. Changes apply immediately and the
  header updates; a rejected value is reported instead of silently kept;
- a bare Escape is now detected on the raw stream. Node's readline never reports
  one — it holds the byte back and folds it into the next key as Alt+key — so
  Escape could not have worked as a mode key without reading the stream directly.

## 1.8.0 - 2026-08-12

The interactive terminal is a real full-screen application.

- a frame compositor draws the whole screen: a fixed header, a scrolling
  transcript, and a bordered input pinned to the bottom. Frames are diffed
  against the last one so only the rows that actually changed are rewritten,
  which is what keeps typing from flickering over SSH;
- the input is a genuine multi-line editor rather than a readline prompt. It
  grows as you type, wraps, and keeps a cursor the compositor can position:
  `⌥⏎` inserts a newline, `⏎` sends, `^W`/`^U`/`^K` delete by word and line,
  `^A`/`^E`/Home/End move, `⌥←`/`⌥→` move by word, Up/Down recall history from
  the buffer edges, `^C` clears a draft before it exits, and `^L` repaints;
- PgUp/PgDn page back through the transcript, and the viewport says how many
  lines are hidden below;
- the header keeps provider, model, controller, permission mode, and workspace
  visible, shortening `$HOME` to `~` and trimming a deep path from the left
  rather than crowding out the status;
- the window is tracked on resize.

It degrades rather than dictates. A pipe, a non-TTY, `--plain`, a screen reader,
or `LOLM_FULLSCREEN=0` all get the linear console instead, and `LOLM_NO_ALT_SCREEN=1`
keeps the frame in the normal scrollback. Nothing here is the only way to use LOLM.

## 1.7.0 - 2026-08-12

The interactive terminal stops corrupting itself, and looks designed.

- background output no longer paints over the line you are typing on. The
  controller finishing its load printed its status *inside* the input prompt,
  because anything written to stdout while readline owns the prompt lands on top
  of it. Async notices now erase the prompt, write above it, and let readline
  repaint it with your typed input intact;
- the console hangs off one shared gutter: labelled rules mark each turn, tool
  timings right-align into a column instead of trailing raggedly, and the header
  pins provider, controller, workspace, and permissions to the edges;
- assistant replies wrap to the terminal width against the same gutter rather
  than relying on terminal soft-wrap;
- plain and ASCII accessibility modes are unchanged and still linear.

Also: `request()` now surfaces HTTP-200 error bodies from OpenAI-compatible
routers (OpenRouter's free tier answers 200 with an `{error}` object and no
choices), retrying a throttle and otherwise raising a classifiable error instead
of failing a turn later as an opaque malformed response.

## 1.6.0 - 2026-08-12

A stray NFET verdict can no longer discard a correct answer.

- the control loop treated every retrieve/verify/branch verdict as a hard order
  to rework. On a task already finished correctly a spurious `branch` told the
  model to try a different approach, and with no memory of what it had produced
  it rebuilt from scratch — once observed proliferating four files for a
  one-file task before hitting the step ceiling;
- once a result is independently verified (its tests pass, or its evidence is
  gathered) the exploratory verdicts are recorded but no longer force more work,
  and each such case is logged as an `nfet.downgraded` event so the decision
  stays honest;
- while a result is still unverified the verdict is honored, but the guidance
  now carries the trajectory ("already edited N files; produced a draft
  beginning …") and forbids discarding correct work or creating redundant files;
- `verify` is gated on the unverified state at both checkpoints, so a verified
  answer is never trapped in a re-check loop;
- a task that says "verify it" now actually forces verification before
  finishing;
- proven with a hermetic test: a stub branch controller and a localhost provider
  drive the real loop and show a verified answer finalizing on the first step
  with zero interventions, while an unverified trajectory is still corrected and
  capped;
- documented that the 4B controller needs memory headroom beside a large local
  model, since the two can thrash a constrained host.

Benchmark honesty: a run that exhausts a provider's tokens-per-day allowance is
now excluded as `usage_limit` rather than scored as model failures — the
classifier previously missed `RATE_LIMITED` and "tokens per day limit exceeded".
Added same-model, same-scaffold ablation tracks (NFET on vs off) for local
Ollama, Cerebras, and Groq so the controller's contribution can be measured
directly; the evidence report labels those as NFET ablations.

## 1.5.0 - 2026-08-12

The terminal is now usable without sight, without colour, and without Unicode.

- `--plain` / `LOLM_PLAIN=1` gives linear, append-only output for a screen
  reader: no alternate screen, no repainting, no cursor movement, no animation,
  and no decorative symbols. Speakers are named ("You:", "LOLM:") and status is
  written as sentences instead of a row of coloured glyphs;
- `TERM=dumb` selects that mode on its own;
- `LOLM_NO_MOTION=1` replaces spinners with one static line every 15 seconds,
  so progress is still reported without a stream of repainted frames;
- a locale that is not UTF-8 now selects an ASCII fallback automatically, and
  typographic characters are folded at the write edge, so box drawing and
  symbols can no longer arrive as mojibake;
- `FORCE_COLOR` is honoured alongside `NO_COLOR`, which keeps colour when piping
  into a pager that understands escapes;
- output is wrapped to the detected width rather than relying on terminal
  soft-wrap, which used to destroy indentation;
- meaning is no longer carried by colour alone: warnings and errors say
  "Warning:" and "Error:", and tool failures name the failure;
- `lolm doctor` reports the detected terminal capabilities and the exact
  variable that changes each one.

## 1.4.0 - 2026-08-12

The NFET controller no longer reloads a 4B model on every command.

- the first run starts a small background service that owns the loaded bridge,
  and later invocations attach to it over a local socket; on an M-series Mac the
  first start measured 92s cold and ~29s with the model in the page cache, while
  attaching and returning a real decision afterwards took under two seconds;
- the Python bridge is now multi-session, so one loaded model serves several
  callers with separate rolling policy state — two LOLM processes sharing the
  service cannot contaminate each other's control decisions;
- there is one service per distinct profile, device, checkpoint, and backend, so
  a differently configured run can never attach to the wrong model;
- the service exits after 30 minutes idle (`LOLM_NFET_IDLE_MS`), can be stopped
  with `lolm nfet stop`, is reported by `lolm nfet status`, and is disabled by
  `LOLM_NFET_DAEMON=0`;
- if the service cannot start, the CLI falls back to a private in-process
  bridge, so NFET degrades in speed rather than availability.

## 1.3.0 - 2026-08-12

Every change below came from watching the agent fail a hidden-test benchmark and
fixing what it exposed, rather than from a feature list.

Reliability:

- code-mode completions are no longer capped at 2000 tokens (800 on Ollama),
  which was smaller than one source file of JSON-escaped content and silently
  cut `fs.write` calls mid-string; the budget is now 8000 hosted and 4000 local
  with a `--max-tokens` override;
- an unparseable tool-argument string is reported as `TOOL_ARGUMENTS_TRUNCATED`
  with the real cause, instead of degrading to `{}` and telling the model it
  forgot a required field — the old behaviour made the model retry the same
  oversized call until the step budget was gone;
- every provider adapter now reports whether the completion hit its token limit;
- rate limits are read from the `retry-after` header, the structured RetryInfo
  duration, or the message prose, with per-attempt deadlines so a request is
  never aborted for waiting out someone else's throttle; a spent daily quota is
  still terminal rather than retried;
- `fs.search` falls back to an equivalent in-process search when ripgrep is not
  installed, where it previously failed outright on most machines.

Control:

- the NFET controller now takes a checkpoint on a tool-failure streak, the
  regime stall it exists to catch and previously never saw, because it only ran
  on text-only turns; when NFET is unavailable the nudge is a plain observation
  and is not attributed to telemetry;
- the controller boots concurrently with the first provider request instead of
  after it.

Tools:

- `fs.patch` recovers the literal text when `old_text` is pasted back from an
  `fs.inspect` preview, and its error now says where to get unnumbered bytes;
- `fs.inspect` gained `line_start` paging and reports `total_lines`;
- Gemini works end to end: tool schemas are projected to the OpenAPI subset the
  API accepts, and Gemini 3.x thought signatures are echoed back on replay.

Benchmark:

- `bench/tasks_hard.py` adds 14 tasks (26 total) covering multi-file repair,
  behaviour-preserving refactors, packages, real CLIs, and test-first work, each
  shipping a reference implementation so `bench/validate.py` proves the hidden
  test is passable and every seeded bug is genuinely broken;
- the cross-agent runner gained Gemini CLI and Claude Code tracks, a same-model
  controlled comparison, an NFET ablation track, and infrastructure-failure
  classification that excludes credential and quota blocks instead of scoring
  them as model losses.

## 1.2.0 - 2026-08-10

- replaced the hard-coded tool switch with a typed registry of 60+ local
  terminal, filesystem, Git, GitHub, Cloudflare, browser, and computer tools;
- added persistent process IDs, exact file patching, dirty-worktree protection,
  task-aware tool routing, execution enforcement, and post-change verification;
- added readonly, standard, developer, and trusted permission modes with
  command classification and explicit production/remote gates;
- added redacted JSONL run events plus `lolm runs`, `run show`, and `run resume`;
- added validated provider setup, macOS Keychain/Secret Service support, richer
  doctor diagnostics, Cerebras model validation, and a clean setup-cancel path;
- added Playwright-powered local Chrome tools, enabled local plugins, and
  explicitly enabled MCP tool servers under the same registry and permissions;
- upgraded the alternate-screen terminal UI with workspace/mode status and live
  tool/process activity while keeping `lolm agent` and `lolm run` simple;
- removed the unsettled top-level-await exit path and preserved the real trained
  NFET telemetry/controller boundary without inventing fallback signals.

## 0.3.0-beta.1 - 2026-07-31

Security hardening release candidate:

- require authenticated principals and isolate persistent workspace data;
- replace permissive saves with complete signed manifests and transactional,
  exact-byte artifact installation;
- fail closed on missing, malformed, incomplete, or contradictory completion
  evidence;
- emit one valid JSON result with correct numeric exit semantics;
- add standards-compliant bounded SSE, request deadlines, idle cancellation, and
  response-size limits;
- verify full SHA-256 and Ed25519 receipts locally, including visual output and
  saved artifact hashes; signing timestamps are now inside the signed core and
  future or missing timestamps fail closed;
- sanitize terminal control sequences and reject unsafe URLs/arguments;
- reject symlinked destination-parent components before staging;
- commit a reproducible npm workspace lock and add a 49,000-assertion release
  gauntlet to cross-platform packaging CI.

Intentional breaking changes are documented in
[`CLI_AUDIT_REMEDIATION.md`](CLI_AUDIT_REMEDIATION.md).
