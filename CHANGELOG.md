# Changelog

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
