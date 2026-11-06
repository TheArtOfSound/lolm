# LOLM security boundary changes — 2026-10-09

This isolated branch is **not yet approved for production**. It hardens the local agent, but does not make Windows shell execution safe for hostile code.

## Implemented
- `--yes`, `developer`, and `trusted` do not authorize shell or external operations without direct human approval. Workspace writes still use their existing permission mode.
- Only complete, allowlisted read-only commands execute automatically; unknown commands, project scripts, shell chaining, variable expansion, environment dumps, and remote changes require approval.
- Even enabled MCP servers and JavaScript plugins must receive direct human trust approval **before** executing their startup code. Non-interactive sessions fail closed rather than assuming `enabled=true` means consent. The requested approval is *for executing host code*, not a promise that the extension's declared read-only tools are harmless.
- Filesystem scope resolves physical symlink paths, including paths to not-yet-existing files.
- The Python sandbox on Windows denies unisolated command execution by default. `LOLM_ALLOW_UNISOLATED_WINDOWS_EXEC=1` is an explicit owner bypass for a trusted local development session, **not** a security sandbox.
- Credential-shaped strings embedded in event stdout get additional masking before run-log persistence. This is best-effort and not a complete secret-leak prevention guarantee.

## Expected behavior changes
Unattended background agents that previously used `--yes` to deploy, execute unknown commands, or start MCP servers will now stop for confirmation rather than act. Do not work around this by automatically approving all prompts. Local sessions are expected to ask on every enabled-extension startup until a signed/pinned extension trust store exists.

Keep GitHub/Cloudflare credentials out of the LOLM host process environment whenever possible, especially on the Windows desktop.

## Verify before merge
```sh
npm ci --ignore-scripts --no-audit --no-fund
npm test --workspace lolm-cli
node clients/js/test/run.mjs
node verification/release_gauntlet.mjs
node --test integrations/chatgpt-readonly-mcp.test.mjs
```
Require green Ubuntu/macOS/Windows Node 20+ CI, Python security checks, and a controlled synthetic-secret exercise. A green workflow does not replace an independent pentest.

## Remaining blockers before a safe unattended Windows launch
1. The **LOLM CLI** still executes approved commands in the host shell; the Python Bubblewrap sandbox does not protect it. Implement a restricted VM/container with narrowly mounted workspaces and no production credentials.
2. Put privileged network, deployment, message, and filesystem actions behind an independent capability broker with scoped credentials, action-level confirmation, replay protection and audit receipts.
3. Add a hash-pinned extension trust registry that invalidates approval when code or MCP config changes. Current branch conservatively prompts every time.
4. Threat-model DNS rebinding and other network boundary issues across all clients.
5. Test actual Windows processes, startup persistence, extensions, encrypted credentials and logs locally. That cannot be verified from GitHub or Cloudflare alone.

**Do not merge or deploy this branch solely on the existence of this document.**
