# lolm-cli

The open-source local LOLM computer-use agent. It runs in your terminal, uses
your chosen model provider directly, and completes work through 60+ typed
terminal, filesystem, Git, GitHub, Cloudflare, browser, and computer tools.
It creates real local artifacts, records durable runs, and uses the repository's
trained NFET monitor as its control loop when available.

```bash
npm install -g lolm-cli
lolm setup
lolm
```

No LOLM account, hosted API key, service credential, or browser app is
required.

In a real terminal, `lolm` and natural requests open the persistent customer
console. Keep talking normally; use `/provider`, `/model`, `/cwd`, `/clear`,
`/mode`, `/debug`, and `/exit` only when you want explicit control. Add `--once` for a
single command response. After a failed task, `lolm try again` restores the
saved prompt, output path, and working directory instead of asking the model
what “try again” means.

## Natural commands

```bash
lolm "answer this: explain state machines simply"
lolm "make me a PDF and put it on my Desktop"
lolm "code an HTML page here" --cwd ./project
lolm "update yourself"
```

## Explicit commands

```bash
lolm ask <question>
lolm agent
lolm run "fix the tests, deploy, and check it in Chrome"
lolm code <task> [--cwd DIR] [--yes] [--dry-run]
lolm pdf <request> [--out FILE]
lolm html <request> [--out FILE]
lolm setup [provider]
lolm providers
lolm models
lolm nfet status|test
lolm doctor [--json]
lolm tools [terminal|fs|git|github|cloudflare|browser|computer]
lolm tools inspect fs.patch
lolm runs
lolm run show RUN_ID
lolm run resume RUN_ID
lolm plugins
lolm mcp list|doctor
lolm config show|set|unset
lolm update [--check]
```

Global provider flags are `--provider`, `--model`, `--api-key`, and
`--base-url`. Permission modes are `readonly`, `standard`, `developer`, and
`trusted`. Built-ins cover OpenAI, Anthropic, Gemini, xAI, OpenRouter,
Groq, Mistral, DeepSeek, Together, Cerebras, Ollama, and arbitrary
OpenAI-compatible endpoints.

`--max-steps N` bounds how many turns one autonomous task may take (default 12)
and `--max-tokens N` overrides the per-completion budget. The default budget is
sized so a whole source file fits in one `fs.write`; raise it for a model that
writes very large files in a single call. If a provider truncates a tool call at
its token limit, the CLI reports `TOOL_ARGUMENTS_TRUNCATED` with the real cause
rather than a misleading schema error, and the model is told to split the work.

`fs.search` uses ripgrep when it is on `PATH` and an equivalent built-in search
otherwise, so code search works on a machine that has never installed `rg`. The
result reports which engine answered.

## NFET

The npm command locates a cloned LOLM repository through `LOLM_HOME`, the
current directory, or common local checkout paths. Its persistent Python bridge
loads the trained graft once and applies the actual LOLM entropy, hidden-drift,
gate, regime, and control-head formulas to candidate output.

```bash
export LOLM_HOME=/path/to/LOLM
lolm nfet status
lolm nfet test "verified result text"
```

The controller takes a checkpoint when a step finishes and again on a streak of
failing tool calls — the stalled trajectory it exists to catch. Its verdict
(`continue`, `retrieve`, `verify`, `branch`, `finalize`) steers the next step.

If the source checkout or trained checkpoint is absent, `doctor` reports the
gap and the CLI labels the monitor unavailable. It never fabricates NFET data:
when the controller is not running, any nudge you see is a plain deterministic
observation and is not presented as telemetry.

The controller loads a 4B backbone, which is not instant — a cold start
measured 92s on an M-series Mac with `device: cpu`. It is warmed in the
background while you type your first message and stays hot for the rest of an
interactive session, so a one-shot `lolm run` pays more of that cost than a
conversation does. Use `--no-nfet` to skip it entirely.

## JSON contract

With `--json`, stdout contains one JSON document and presentation stays off.
Successful commands use `{ "ok": true, ... }`. Errors use:

```json
{"ok":false,"error":{"code":"AUTH_MISSING","message":"..."}}
```

Credentials are validated before setup is saved and are never included in
output. On macOS, entered keys use Keychain; systems without an available native
secret service fall back to the mode-0600 local config. Provider diagnostics
report only whether a key exists and its source.
Local file operations and commands stay on the machine. A selected remote
provider still receives the prompt and context sent for inference; choose
Ollama when the inference itself must remain local.

## Tool and extension architecture

Every built-in action is registered with a canonical name, JSON schema, risk
class, and executor. The model receives task-relevant tools instead of one
unrestricted shell escape hatch. `terminal.spawn` returns a process ID used by
`terminal.status`, `terminal.stdin`, and `terminal.kill`; file changes support
exact patching; Git protects dirty worktrees; deploys and remote mutations use
explicit approval gates. Browser tools launch local Chrome through
`playwright-core` and remain in the same agent loop.

Enabled `lolm-plugin.json` manifests under `.lolm/plugins` or
`~/.lolm/plugins` can add typed tools. Explicitly enabled servers in `.mcp.json`
can do the same over MCP. Their tools still pass through LOLM's schema
validation, risk classification, event log, and permission policy.

## License

AGPL-3.0-or-later © 2026 Bryan Leonard & Brandyn Leonard — Qira LLC.
Alternative commercial terms are available by inquiry; see the repository's
`COMMERCIAL-LICENSE.md`.
