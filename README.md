# LOLM — local intelligence that does not lose the plot

LOLM is an open-source, local-first AI agent with its own terminal interface,
provider-agnostic API keys, local coding tools, artifact creation, and a real
NFET control loop. The public website is documentation only; your prompts,
files, commands, and provider credentials stay on your computer.

```bash
npm install -g lolm-cli
lolm setup
lolm
```

Then speak naturally:

```bash
lolm "answer this: why does the sky look blue?"
lolm "make me a PDF project brief and put it on my Desktop"
lolm "code a polished HTML page here" --cwd ./my-project
lolm "update yourself"
```

Explicit commands are available when you want predictable scripting:

```bash
lolm ask "explain this repository"
lolm code "fix the failing tests" --cwd .
lolm pdf "write a launch plan" --out ~/Desktop/launch-plan.pdf
lolm html "build a personal landing page" --out ./index.html
lolm doctor --json
```

## Bring any model

LOLM supports OpenAI, Anthropic, Google Gemini, xAI, OpenRouter, Groq,
Mistral, DeepSeek, Together AI, Cerebras, Ollama, and custom
OpenAI-compatible endpoints. Credentials resolve in this order:

1. the provider's normal environment variable;
2. `~/.lolm/config.json` written with mode `0600` by `lolm setup`;
3. `--api-key` for one-off use.

```bash
export ANTHROPIC_API_KEY=...
lolm setup anthropic

export OPENROUTER_API_KEY=...
lolm setup openrouter

lolm setup ollama               # no key; local model server
lolm setup custom --base-url http://127.0.0.1:8000/v1 --model my-model
```

Run `lolm providers` and `lolm models` to discover the live options. LOLM does
not require a LOLM account, license key, subscription, or hosted API.

## NFET is the controller, not decoration

Provider models supply language capability. The local LOLM-NFET graft re-reads
their candidate output and measures, per token:

- logit entropy;
- corrected-hidden drift;
- manifestation-gate balance;
- regime entropy;
- trained control-head logits.

The existing rolling, calibrated `NFETControlPolicy` turns those measurements
into `continue`, `retrieve`, `verify`, `branch`, or `finalize`. The CLI acts on
those decisions and shows them in the terminal. Pointwise head outputs cannot
force disruptive actions without rolling telemetry support, and `finalize`
still requires normal completion checks.

For the full local monitor, clone this repository and point the npm CLI to it:

```bash
git clone https://github.com/TheArtOfSound/LOLM.git
cd LOLM
python3 -m venv .venv
.venv/bin/pip install -r requirements-agent.txt
export LOLM_HOME="$PWD"
lolm nfet status
lolm nfet test "The implementation is complete and tests passed."
```

On Apple Silicon, the trained 4B profile defaults to
`qwen3_4b_lab` + MPS + `runs/nfet_controller/live_qwen4b.pt` + `gru_debug`.
Change these with `lolm config set nfet-profile`, `nfet-device`, and
`nfet-checkpoint`. If the local model or checkpoint is unavailable, the CLI
reports NFET as unavailable; it never substitutes invented telemetry.

## Local safety model

- Read-only inspection tools run directly.
- File writes and shell commands require approval unless `--yes` is supplied.
- Broad destructive commands are blocked even with `--yes`.
- Files are written atomically.
- `--dry-run` previews mutations.
- API keys are redacted from diagnostics and JSON output.
- `--json` emits one stable machine-readable result.
- `--no-nfet` is an explicit opt-out, not a silent fallback.

## Repository map

```text
clients/cli/                 npm CLI and terminal UI
  bin/lolm.mjs               command router and interactive console
  lib/providers.mjs          provider adapters
  lib/agent.mjs              local tool/NFET agent loop
  lib/nfet_bridge.py         real Python NFET telemetry bridge
  lib/tools.mjs              local file, shell, and web tools
  lib/pdf.mjs                guaranteed local PDF writer
lolm/                        LOLM model and NFET policy
local_ui/                    Python local runtime and MCP server
site/                        install/docs/research website (no execution)
configs/                     model and training profiles
tests/                       Python architecture and agent tests
```

## Develop and verify

```bash
npm install
npm test --workspace lolm-cli
PYTHONPATH="$(pwd):$(dirname "$(pwd)")" .venv/bin/python -m pytest -q tests
```

LOLM is available under AGPL-3.0-or-later, with a separate commercial license
for organizations that want to embed or host it without AGPL source-sharing
obligations. See [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md). There are no
public price cards or self-serve checkout. See [SECURITY.md](SECURITY.md) for
reporting and operational guidance.

## Research architecture

LOLM separates surface token prediction from latent state tracking through a
Transformer decoder, selective state-space core, discrete regimes, persistent
memory, and a learned manifestation gate. Research configs, evaluation scripts,
ablation studies, and the NFET training flywheel remain in this repository.

```bibtex
@article{leonard2026lolm,
  title  = {LOLM: Language Modeling Beyond the Surface with Hybrid Transformer-SSM Latent Order Fields},
  author = {Leonard, Bryan and Leonard, Brandyn},
  year   = {2026},
  note   = {Qira LLC. Code: https://github.com/TheArtOfSound/LOLM}
}
```

## License

[AGPL-3.0-or-later](LICENSE) © 2026 Bryan Leonard & Brandyn Leonard — Qira LLC.
Alternative commercial terms are available by inquiry.
