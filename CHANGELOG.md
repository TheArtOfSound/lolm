# Changelog

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
