# ChatGPT ↔ LOLM: private read-only MCP bridge

LOLM has an existing local MCP server (local_ui/mcp_server.py) with broad
capabilities. Do not expose that unrestricted server remotely as a first step.
This small adapter (integrations/chatgpt-readonly-mcp.mjs) exposes only four
strictly allowlisted functions via standard input/output.

## Exposed tools

| Tool | Operation |
| --- | --- |
| lolm_bridge_info | Confirm the bridge's exact capabilities |
| lolm_diagnostics | Fixed LOLM doctor --json; only safe readiness fields returned |
| lolm_nfet_status | Fixed NFET status --json; local paths and credentials omitted |
| lolm_nfet_check | Evaluate 1–1400 non-secret characters with existing NFET monitor |

No arbitrary shell, file read/write, local memory dump, credential access,
remote command execution, deployment, or general-purpose agent tools.
NFET checks can start a local model monitor and consume CPU/GPU resources.

## Step 1 — Use an isolated LOLM checkout on the Mac

To avoid disturbing a live LOLM installation or other running services, use
a **separate** checkout for the ChatGPT bridge. This is a shallow clone with
no repository history beyond the current main branch:

    mkdir -p "$HOME/ChatGPT-bridges"
    git clone --depth 1 --filter=blob:none       https://github.com/TheArtOfSound/LOLM.git       "$HOME/ChatGPT-bridges/lolm"

If that bridge checkout ALREADY exists, do not clone into it again. Instead
update it only if its working tree is clean:

    cd "$HOME/ChatGPT-bridges/lolm"
    git status --short
    git pull --ff-only origin main

Do not run git switch, git reset, npm update or deploy scripts in a different,
active LOLM checkout. In the isolated bridge checkout run:

    cd "$HOME/ChatGPT-bridges/lolm"
    node --version
    node --test integrations/chatgpt-readonly-mcp.test.mjs
    node clients/cli/bin/lolm.mjs doctor --json
    node clients/cli/bin/lolm.mjs nfet status --json

Node 20+ is required. The bridge CLI may need its normal npm workspace
dependencies. If the CLI reports a missing module, install dependencies
**inside this isolated checkout only**; do not modify live services.

If the trained LOLM/NFET checkpoint is in another active checkout, configure
LOLM_HOME for this bridge process to point at that existing source directory.
Do not move or copy multi-gigabyte model files just for tunnel setup.

A missing NFET checkpoint may correctly report available=false; do not claim
a successful NFET check until it actually works.

## Step 2 — Secure MCP Tunnel (outbound-only)

Official guide:
https://developers.openai.com/api/docs/guides/secure-mcp-tunnels

In OpenAI Platform tunnel settings, provision the tunnel and obtain its actual
tunnel_id and a runtime API key. The Platform organization needs the appropriate
tunnel permissions, and the ChatGPT workspace must allow custom MCP plugins.

Download the current compatible macOS tunnel-client binary from:
https://github.com/openai/tunnel-client/releases/latest

Run tunnel-client help quickstart. Enter your key only locally, never in chat,
GitHub commits or CLI transcripts. Example for zsh:

    cd /ABSOLUTE/PATH/TO/LOLM
    read -rs "CONTROL_PLANE_API_KEY?Tunnel runtime API key: "
    echo
    export CONTROL_PLANE_API_KEY

    tunnel-client init \
      --sample sample_mcp_stdio_local \
      --profile lolm-readonly \
      --tunnel-id YOUR_REAL_TUNNEL_ID \
      --mcp-command "node $PWD/integrations/chatgpt-readonly-mcp.mjs"

    tunnel-client doctor --profile lolm-readonly --explain
    tunnel-client run --profile lolm-readonly

The tunnel process must remain running. It initiates outbound HTTPS to OpenAI.
No public HTTP port, Cloudflare route or DNS change is required.

If Platform tunnels are unavailable or the account does not have the necessary
permission, stop and report that exact blocker; do not publish an open tunnel.

## Step 3 — Add the tunnel in ChatGPT

1. In ChatGPT on the web, open Plugins.
2. Press + → Add custom MCP server.
3. Name it LOLM Local (Read Only).
4. Under Connection choose Tunnel and select your provisioned tunnel.
5. Configure authentication, review the risk warning and create the plugin.
6. Install/connect it. Inspect the discovered tool list: exactly FOUR tools.

Plugin creation and consent require user authorization in ChatGPT. Neither
the GitHub nor Cloudflare connector can complete these account-specific clicks.

ChatGPT documentation:
https://developers.openai.com/api/docs/guides/custom-mcp-server

## Step 4 — Verify end-to-end

Once the plugin appears connected in ChatGPT, test in order:

1. "Use LOLM Local (Read Only) to call lolm_bridge_info."
2. "Use LOLM Local (Read Only) to call lolm_nfet_status."
3. Only if available: "Use LOLM Local (Read Only) to run lolm_nfet_check
   with text 'Review this plan: no external actions; verify constraints.'"

Acceptance gates:
- All four tools are discovered; none execute arbitrary commands.
- LOLM status has live values and no sensitive file paths or provider keys.
- NFET returns a real decision or a clear unavailable/error result.
- A connected tunnel alone is NOT evidence the trained controller is running.

## Stop / revoke

Stop tunnel-client with Ctrl+C. Disable or uninstall the custom plugin.
Revoke the runtime key and tunnel in OpenAI Platform when no longer needed.
This adapter makes no Cloudflare, DNS, site or local source changes by running.

The adapter is designed for one trusted operator. Requests to expose file,
shell, memory, write, or deployment tools require a separately reviewed
implementation and tool-level permissions, not unrestricted MCP forwarding.

Source: integrations/chatgpt-readonly-mcp.mjs
Test: node --test integrations/chatgpt-readonly-mcp.test.mjs
Last reviewed: October 2026.
