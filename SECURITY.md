# Security policy

## Supported security line

The hardened CLI and JavaScript client begin at `0.3.0-beta.1`. The beta is not
labeled pipeline-safe until its release commit passes the cross-platform and
clean-package gates described in
[`CLI_AUDIT_REMEDIATION.md`](CLI_AUDIT_REMEDIATION.md).

## Trust boundaries

- Persistent workspace data is keyed by a validated `X-LOLM-Api-Key` (or Bearer
  token). Client-provided owner names are not authorization.
- A server result is untrusted until the CLI verifies its canonical full SHA-256,
  Ed25519 signature, signed timestamp policy, schema, run binding, and explicit
  success fields.
- Artifact paths and contents are server-controlled input. Saves use a fresh
  destination, strict relative paths, bounded exact bodies, staging, and full
  verification before atomic commit. Symlinked destination-parent components
  are refused.
- Terminal text is untrusted. Human rendering removes terminal and bidi controls;
  exact raw artifact output is allowed only to redirected stdout.
- Network input is bounded by response/event/stream sizes, total deadlines, idle
  deadlines, and cancellation.

Operators should pin trusted receipt public keys with
`LOLM_RECEIPT_PUBLIC_KEYS=key-id:base64url-key` for offline or high-assurance
verification. Protect `LOLM_RECEIPT_SIGNING_KEYS` as a signing secret and rotate
key IDs; never distribute it to clients.

## Reporting a vulnerability

Do not include live API keys, signing keys, licenses, private prompts, or saved
artifacts in a public issue. Use the private contact listed at
<https://imagineqira.com/#contact> with the affected version, reproduction, and
impact. Revoke any credential that may have been exposed.
