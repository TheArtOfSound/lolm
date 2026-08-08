# lolm-cli

The open-source local LOLM agent. It runs in your terminal, uses your chosen
model provider directly, operates on local files with approval, creates real
local artifacts, and uses the repository's trained NFET monitor as its control
loop when available.

```bash
npm install -g lolm-cli
lolm setup
lolm
```

No LOLM account, hosted API key, service credential, or browser app is
required.

In a real terminal, `lolm` and natural requests open the persistent customer
console. Keep talking normally; use `/provider`, `/model`, `/cwd`, `/clear`,
`/debug`, and `/exit` only when you want explicit control. Add `--once` for a
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
lolm code <task> [--cwd DIR] [--yes] [--dry-run]
lolm pdf <request> [--out FILE]
lolm html <request> [--out FILE]
lolm setup [provider]
lolm providers
lolm models
lolm nfet status|test
lolm doctor [--json]
lolm config show|set|unset
lolm update [--check]
```

Global provider flags are `--provider`, `--model`, `--api-key`, and
`--base-url`. Built-ins cover OpenAI, Anthropic, Gemini, xAI, OpenRouter,
Groq, Mistral, DeepSeek, Together, Cerebras, Ollama, and arbitrary
OpenAI-compatible endpoints.

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

If the source checkout or trained checkpoint is absent, `doctor` reports the
gap and the CLI labels the monitor unavailable. It never fabricates NFET data.

## JSON contract

With `--json`, stdout contains one JSON document and presentation stays off.
Successful commands use `{ "ok": true, ... }`. Errors use:

```json
{"ok":false,"error":{"code":"AUTH_MISSING","message":"..."}}
```

Credentials are never included. Provider diagnostics report only whether a key
exists and whether it came from a flag, environment, config, or was not needed.
Local file operations and commands stay on the machine. A selected remote
provider still receives the prompt and context sent for inference; choose
Ollama when the inference itself must remain local.

## License

AGPL-3.0-or-later © 2026 Bryan Leonard & Brandyn Leonard — Qira LLC.
Alternative commercial terms are available by inquiry; see the repository's
`COMMERCIAL-LICENSE.md`.
