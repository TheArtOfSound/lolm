# Independent CLI release verification - 2026-08-01

## Verdict

**Substantially hardened, still alpha.** The committed candidate passes the
clean-clone, packed-package, fail-closed, filesystem, receipt, SSE, terminal,
and exact-artifact checks run locally. It is not a release candidate and must
not be called pipeline-safe because the production service is still on the
legacy protocol and still exposes persistent workspace data anonymously.

Tested code commit: `d8a52c2b7f0f75fd075579986d146fa8a31d060b` on
`codex/cli-hardening-remediation`.

## Clean-clone and packaged evidence

The branch was cloned with `git clone --no-local` into a new temporary tree.
No dirty working-tree files were present in that clone.

- `npm ci`: passed from the committed workspace lock.
- `npm test`: passed - JavaScript client `15/15`, CLI `42/42`, release
  gauntlet `49,000/49,000` assertions.
- Clean-clone Python suite: `508 passed, 2 skipped`.
- `npm pack` produced `lolm-nfet-client-0.3.0-beta.1.tgz` (5 files) and
  `lolm-cli-0.3.0-beta.1.tgz` (11 files).
- Tarball inventory contained only declared runtime code, licenses, READMEs,
  and package metadata. No environment files, databases, logs, local receipts,
  tests, temporary data, or `node_modules` were present.
- Both tarballs installed into an unrelated project whose path contains spaces,
  a quote, Unicode, and a long component.
- Local binary, `npx lolm-cli`, combined global tarball install, and read-only
  working-directory help invocation all passed.
- The installed tarballs passed the full 49,000-assertion gauntlet on macOS
  arm64 with Node `20.20.2`, `22.23.2`, and `25.9.0`.
- A real mutation replacing the strict shipped predicate with
  `done.ok || receipt.verdict === "shipped"` failed immediately on truth-table
  case 1. The suite therefore kills the original optimistic-success defect.

Gauntlet campaign counts:

| Campaign | Cases |
|---|---:|
| Exit/receipt/artifact truth table | 43,740 |
| Generated filesystem campaign | 5,019 |
| SSE framing and chunk boundaries | 110 |
| Parser and process matrix | 77 |
| Receipt tampering | 20 |
| Terminal-control payloads | 16 |
| Exact artifact fidelity and staging | 16 |
| Total assertions | 49,000 |

The gauntlet source is `verification/release_gauntlet.mjs` and can target an
installed package via `LOLM_PACKAGE_ROOT` and `LOLM_JS_ROOT`.

## Audit finding disposition at the tested commit

| Finding | Final commit disposition | Live deployment disposition |
|---|---|---|
| AUTH-001 | Fixed | Not fixed |
| AUTH-002 | Fixed | Not fixed |
| FS-001 | Fixed | Not evaluated on legacy deployment |
| FS-002 | Fixed | Not evaluated on legacy deployment |
| VERDICT-001 | Fixed | Hardened CLI fails closed against legacy responses |
| JSON-001 | Fixed | Fixed in candidate CLI |
| JSON-002 | Fixed | Fixed in candidate CLI |
| SAVE-001 | Fixed | Blocked by legacy receipt protocol |
| SAVE-002 | Fixed | Blocked by legacy receipt protocol |
| TERM-001 | Fixed | Fixed in candidate CLI |
| RECEIPT-001 | Partially fixed | Not fixed |
| BUILD-001 | Fixed | Blocked by legacy receipt protocol |
| BUILD-002 | Fixed | Fixed in candidate CLI |
| NET-001 | Fixed | Fixed in candidate CLI |
| SSE-001 | Fixed | Fixed in candidate client |
| ARG-001 | Fixed | Fixed in candidate CLI |
| ARG-002 | Fixed | Fixed in candidate CLI |
| ARG-003 | Fixed | Fixed in candidate CLI |
| ARG-004 | Fixed | Fixed in candidate CLI |
| URL-001 | Fixed | Fixed in candidate CLI |
| DIFF-001 | No longer applicable to canonical save | Same |
| DIFF-002 | No longer applicable to canonical save | Same |
| DIFF-003 | Fixed | Blocked by legacy receipt protocol |
| DIFF-004 | Fixed | Blocked by legacy receipt protocol |
| CLIENT-001 | Fixed | Fixed in candidate client |
| PIPE-001 | Fixed | Fixed in candidate CLI |
| SCALE-001 | Fixed | Fixed in candidate client/CLI |
| CI-001 | Partially fixed | Workflow exists; no hosted run evidence yet |

`RECEIPT-001` remains partial because local SHA-256, Ed25519, signed timestamp,
schema, verdict, run, and artifact binding are verified, but default online key
discovery comes from the same service unless the operator pins a public key.
Ledger fields are displayed as links, not claimed as independently chain-
verified. That limitation is documented and still blocks a stronger claim.

## Live hosted-service evidence

Read-only probes against `https://lolm.imagineqira.com` showed:

- `/api/demo/status` returned HTTP 200 and the candidate `status --json`
  command exited 0.
- `/api/demo/receipts/keys` still advertises legacy `HS256` and no Ed25519 key
  list compatible with the candidate protocol.
- Recent receipts still use the legacy short-hash/no-v2-schema shape.
- A bounded live code task completed server-side, but the candidate CLI exited
  1 because the response lacked the v2 schema, run binding, required signed
  verification fields, and independently usable public key. This is the
  correct fail-closed client behavior.
- Anonymous GET requests to workspace memory and conversation-list endpoints
  returned HTTP 200 with persistent data. No mutation was attempted. This is a
  live P0 confidentiality blocker.

The planned 160 live coding runs were not started after these blockers were
confirmed: the currently deployed service cannot satisfy the first receipt or
authentication release gate, so additional model runs would consume quota
without producing release evidence.

## Original 132-scenario limitation

The PDF contains 90 process rows, 34 HTTP/SSE rows, and 8 direct SSE fixtures.
Those counts overlap; the source JSON files named in the PDF
(`lolm_cli_mock_stress_results.json` and `lolm_cli_e2e_results.json`) and the
original harness were not present in the repository, Downloads, or elsewhere
under the local user tree. The named defect classes and original exploit forms
were reconstructed into permanent tests and the larger generated gauntlet, but
this report does **not** claim that the unavailable original harness was rerun
byte-for-byte.

## Remaining release blockers

1. Deploy the authentication, Ed25519 receipt v2, artifact-manifest, and
   workspace-ownership changes to the hosted service.
2. Immediately contain the anonymous production memory/conversation endpoints
   during that deployment.
3. Push the exact branch and obtain green Linux, macOS, and Windows Node 20/22
   workflow runs. Local macOS runtime substitution is not Windows/Linux proof.
4. Publish `lolm-nfet-client@0.3.0-beta.1` before or atomically with
   `lolm-cli@0.3.0-beta.1`; a CLI-only global install cannot resolve an
   unpublished dependency. The two local tarballs install together correctly.
5. Recover the original 90/34 JSON results and harness if byte-for-byte replay
   is a mandatory release record.
6. After deployment, run the balanced live task campaign and independently
   compare receipt hashes, files, local execution, and exit status.

Until these items pass, the allowed public wording remains **developer preview
/ hardened alpha**, not release candidate or pipeline-safe.
