# Changelog

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
