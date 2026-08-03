# lolm-cli

Hardened beta control console for the LOLM agent. Version `0.3.0-beta.2`
fails closed on incomplete streams and receipts, verifies signed artifacts before
installing them, delivers requested files to the local machine, and preserves the
last delivered path for cross-command follow-ups.

The beta is deliberately **not described as pipeline-safe**. That label remains
blocked until the release workflow has passed on Linux, macOS, and Windows and
the packed CLI has passed its clean-install smoke test.

```bash
npm install -g lolm-cli
export LOLM_API_KEY=lolm_…
lolm doctor

# Artifact requests now choose a fresh verified local destination automatically.
lolm code "create a PDF report and put it on my Desktop"
lolm ask "where is the PDF?"
lolm artifact open

# Explicit destinations remain supported.
lolm code "write fizzbuzz to 20 in solution.py and run it" --save ./out
lolm receipt verify ./run.receipt.json
```

## Artifact delivery

When a `code` request explicitly asks for a PDF, document, spreadsheet,
presentation, image, HTML file, or another user-facing artifact and no `--save`
flag is supplied, the launcher creates a fresh destination under the requested
Desktop, Downloads, or Documents folder. Downloads is the default when no local
folder was named.

The CLI reports delivery only after:

1. the hosted run emits a complete artifact manifest;
2. the signed receipt binds that manifest;
3. every file body matches its declared byte count and SHA-256;
4. installation commits atomically on the local machine; and
5. at least one file matches the requested artifact type.

Generated source code without the requested PDF/document is not reported as a
delivered success. The last verified local path is stored in
`~/.lolm/deliveries.json` with mode `0600`, enabling:

- `lolm ask "where is the PDF?"`
- `lolm artifact last`
- `lolm artifact open` on macOS

Official credential fabrication is blocked before any remote model or tool call.
LOLM may create a clearly labeled unofficial self-attestation, draft a request
for genuine verification, or assemble authentic evidence supplied by the user.

## Security contract

- `--save` accepts only a complete `lolm.artifact.manifest.v1` bound to a locally
  verified Ed25519 receipt. Absolute, traversal, reserved, colliding, NUL, and
  oversized paths are rejected. Installation stages into a private sibling
  directory, verifies every full SHA-256, and atomically renames only after all
  files pass.
- The destination must not exist. This intentional breaking change prevents
  symlink traversal, partial replacement, deletion ambiguity, and unsafe
  overwrites. Choose a fresh directory and move it into place in your own
  deployment transaction.
- `code` exits `0` only when `code_done` and `code_receipt` are both present,
  their run IDs match, every required verification field is explicitly true,
  the signed timestamp is present and not in the future, the receipt hash and
  signature verify locally, and a requested save verifies.
- `build` writes or streams HTML only after the visual receipt, run binding,
  byte count, browser verdict, signature, and content hash all verify. Raw
  `--stdout` output is refused on a terminal; redirect it to a file or pipe.
- Human output removes CSI, OSC, DCS, APC, PM, C0/C1, carriage-return, and bidi
  controls. JSON output contains exactly one complete JSON document.
- Requests default to a 120-second total deadline and streaming calls to a
  30-second idle deadline. Use `--timeout` and `--idle-timeout` within the
  documented bounds.
- Persistent memory requires `X-LOLM-Api-Key`; caller-supplied owner namespaces
  are ignored.

## Commands

- `lolm doctor`
- `lolm code <task> [--save <new-dir>] [--receipt <file>]`
- `lolm ask <question> [--fail-on red]`
- `lolm artifact last|open`
- `lolm build <task> [--out <new-file> | --stdout]`
- `lolm receipt verify <file|sha-prefix>`
- `lolm receipts`, `status`, `whoami`, `config`
- `lolm inspect task --id <task_id> | --conversation <id>`
- `lolm memory list|add|forget`

Use `--trace` on a `code` command to retain the full controller and sandbox event
stream. Default artifact runs use the quieter user-facing presentation.

Unknown flags, missing values, non-integers, values outside their bounds, and
unsafe base URLs exit `2` before a request is made. HTTP is accepted only for
loopback development; remote origins require HTTPS. Use `--` before prompt text
that begins with `-`.

## Identity and receipt keys

```bash
export LOLM_API_KEY=lolm_…
export LOLM_LICENSE=…

# Optional pinned public keys for offline/high-assurance verification:
export LOLM_RECEIPT_PUBLIC_KEYS='key-id:base64url-public-key'
lolm receipt verify ./run.receipt.json
```

The CLI never asks the receipt issuer to attest its own signature. It fetches
public key material when online (or uses pinned environment keys), recomputes the
canonical full SHA-256, and verifies Ed25519 locally. Unknown keys fail closed.

## Exit codes

- `0`: the command's complete success contract passed
- `1`: remote failure, malformed/incomplete/contradictory evidence, failed gate,
  invalid receipt, missing requested artifact, or verification failure
- `2`: usage or argument error, including blocked credential fabrication
- `124`: total or idle timeout
- `130` / `143`: clean SIGINT / SIGTERM cancellation

## Tests and packaging

```bash
npm ci
npm test --workspace lolm-nfet-client
npm test --workspace lolm-cli
npm run test:release-gauntlet
npm pack --dry-run --prefix clients/js
npm pack --dry-run --prefix clients/cli
```

See the [audit remediation matrix](https://github.com/TheArtOfSound/lolm/blob/main/CLI_AUDIT_REMEDIATION.md)
for the finding-by-finding disposition and release gates.
