# CLI adversarial audit remediation

This document maps every finding in
`LOLM_CLI_Adversarial_Audit_and_Remediation_Plan.pdf` to the repository as it
existed when the hardening branch began, then records the implemented control.
“Confirmed” means the vulnerable behavior still existed in the current checkout;
“partially fixed” means newer uncommitted work addressed only part of it;
“already fixed” means current code had overtaken the audit before this branch.

## Finding disposition

| Finding | Current-checkout status at start | Remediation and acceptance evidence |
|---|---|---|
| AUTH-001 | Confirmed | Every persistent workspace/memory route now requires a valid API key and returns `401` anonymously. |
| AUTH-002 | Confirmed | Ownership derives only from the validated key ID. Owner headers/body fields are ignored; cross-principal object access returns `404`. A dedicated endpoint mints browser principal keys. |
| FS-001 | Confirmed | Artifact paths reject POSIX/Windows absolute paths, UNC, traversal, NUL, empty/dot segments, reserved names, and component limits. |
| FS-002 | Confirmed | Save uses a private sibling staging tree, `wx` regular files, pre/post full-hash verification, and atomic rename. Existing or symlink destinations are refused. |
| VERDICT-001 | Confirmed | Exit `0` requires matching `code_done`/receipt run IDs and every explicit signed success field. Missing, false, malformed, or contradictory evidence fails closed. |
| JSON-001 | Confirmed | JSON mode emits exactly one `lolm.cli.result.v2` document; progress goes to stderr and is suppressed from stdout. |
| JSON-002 | Confirmed | The CLI sets numeric `process.exitCode`; it no longer assigns an object or terminates before writes drain. |
| SAVE-001 | Confirmed | `artifact_manifest` events are collected even in `--json` mode; save and JSON now compose. |
| SAVE-002 | Confirmed | `--save` no longer reconstructs from display diffs. It consumes only the complete canonical final-tree manifest. |
| TERM-001 | Confirmed | Human-mode untrusted output strips ANSI CSI, OSC, DCS/APC/PM, C0/C1, carriage returns, and bidi controls. Raw build stdout is refused on a TTY. |
| RECEIPT-001 | Partially fixed | Preliminary short hashes/HMAC attestation were replaced by full canonical SHA-256 plus Ed25519. Verification is local using public material; issuer attestation is not trusted. |
| BUILD-001 | Confirmed | Build output is withheld until a signed visual receipt, browser verdict, run binding, byte count, and HTML hash verify locally. |
| BUILD-002 | Confirmed | Build now has one explicit contract: verified HTML is written to a new file by default; `--stdout` emits raw HTML only when redirected, and the README examples match it. |
| NET-001 | Confirmed | Every client fetch has a bounded total timeout; SSE streams also have idle timeouts. Abort signals propagate and readers clean up. |
| SSE-001 | Confirmed | The parser implements CR/LF/CRLF framing, multiline data, comments, optional spaces, arbitrary chunking, UTF-8 flush, and EOF dispatch. |
| ARG-001 | Confirmed | Missing option values and option-looking would-be values are rejected before a command handler runs. |
| ARG-002 | Confirmed | Numeric options use strict finite decimal-integer parsing with explicit positive upper/lower bounds. |
| ARG-003 | Confirmed | `--` preserves arbitrary option-looking UTF-8 prompt text as literal input. |
| ARG-004 | Confirmed | Flags are command-scoped; unknown, irrelevant, and extra positional arguments fail before network activity. |
| URL-001 | Confirmed | Remote bases require HTTPS; HTTP is accepted only for loopback. Credentials, query, fragment, and non-origin paths are rejected. |
| DIFF-001 | Already fixed | Trailing-newline presence/absence was already preserved by the newer diff engine; canonical manifests now preserve exact bytes independently of display diffs. |
| DIFF-002 | Already fixed | Explicit deletion handling was already present in the newer working tree; final-tree manifests make deletion unambiguous by installing a fresh destination. |
| DIFF-003 | Confirmed | Canonical save validates the full manifest, writes into a fresh private staging tree, verifies every byte, and atomically renames only the complete tree. |
| DIFF-004 | Confirmed | Canonical manifests, rather than display-oriented/truncated diffs, carry complete text or binary artifact bytes. |
| CLIENT-001 | Confirmed | `runAgent`, `runCode`, and `buildVisual` require their terminal event(s) and return typed protocol errors otherwise. |
| PIPE-001 | Confirmed | Large JSON uses a single drained write path; EPIPE is handled without a stack trace or false failure. |
| SCALE-001 | Confirmed | JSON, event, stream, file-count, per-file, total-artifact, and path-component limits are enforced. |
| CI-001 | Confirmed | `cli-security.yml` adds Node 20/22 on Linux, macOS, and Windows plus clean tarball installation; Python security tests run on Linux. |

## Intentional compatibility breaks

1. Persistent memory and workspace operations require an API key. Arbitrary
   `owner` values no longer select a namespace.
2. `--save` requires a new destination. `--force` was removed because overwriting
   an existing/symlinked tree cannot preserve the new all-or-nothing contract.
3. Unsigned, legacy HMAC, short-hash, incomplete, unknown-key, or contradictory
   receipts cannot authorize success.
4. Artifact manifests with omitted bodies, size-budget omissions, path
   collisions, or non-authoritative hashes make the run non-shippable.
5. Remote plaintext HTTP base URLs are rejected.

## Release blockers

The implementation and local acceptance suites pass, but the public label
“pipeline-safe” remains prohibited until the cross-platform workflow and packed
clean-install job pass for the release commit. Publishing and hosted-production
verification are separate, credentialed release actions and were not inferred
from this repository remediation.

The release gate is:

```bash
npm ci
npm test --workspace lolm-nfet-client
npm test --workspace lolm-cli
npm run test:release-gauntlet
PYTHONPATH="$(pwd):$(dirname "$(pwd)")" .venv/bin/python -m pytest -q tests
npm pack --dry-run --prefix clients/js
npm pack --dry-run --prefix clients/cli
```
