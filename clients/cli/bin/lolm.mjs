#!/usr/bin/env node
// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** LOLM: local, open-source, BYOK agent with real NFET control. */
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { homedir } from "node:os";
import { spawn } from "node:child_process";
import process from "node:process";
import readline from "node:readline/promises";
import { fileURLToPath } from "node:url";
import { runAgent, generateDocument, generateHtml } from "../lib/agent.mjs";
import { CONFIG_PATH, PROVIDERS, loadConfig, publicRuntime, resolveRuntime, saveConfig, normalizeProvider } from "../lib/config.mjs";
import { listModels, rawGet, ProviderError } from "../lib/providers.mjs";
import { NfetMonitor, inspectNfet } from "../lib/nfet.mjs";
import { createPdf } from "../lib/pdf.mjs";
import { isRetryPhrase, loadLastTask, saveLastTask } from "../lib/session.mjs";
import { nativeSecretBackend, storeProviderSecret } from "../lib/secrets.mjs";
import { collectDiagnostics } from "../lib/diagnostics.mjs";
import { createAgentToolbox } from "../lib/tools/index.mjs";
import { RunStore } from "../lib/runtime/runs.mjs";
import { PERMISSION_MODES } from "../lib/runtime/permissions.mjs";
import { readMcpConfig } from "../lib/mcp.mjs";
import { banner, confirm, createConsoleSurface, failure, nfetLine, note, prompt as askPrompt, renderMarkdown, secretPrompt, section, spinner, success, ui, warning, wordmark } from "../lib/tui.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const VERSION = pkg.version;

const VALUE_FLAGS = new Set(["--provider", "--model", "--api-key", "--base-url", "--cwd", "--out", "-o", "--timeout", "--max-steps", "--mode"]);
const BOOLEAN_FLAGS = new Set(["--json", "--yes", "-y", "--dry-run", "--check", "--open", "--help", "-h", "--version", "-V", "--no-nfet", "--once"]);

function parse(argv) {
  const flags = { cwd: process.cwd(), maxSteps: 12 };
  const words = [];
  let literal = false;
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (token === "--" && !literal) { literal = true; continue; }
    if (!literal && VALUE_FLAGS.has(token)) {
      const value = argv[++i];
      if (value == null) throw Object.assign(new Error(`${token} requires a value`), { exitCode: 2 });
      const key = ({ "--provider": "provider", "--model": "model", "--api-key": "apiKey", "--base-url": "baseUrl", "--cwd": "cwd", "--out": "out", "-o": "out", "--timeout": "timeout", "--max-steps": "maxSteps", "--mode": "permissionMode" })[token];
      flags[key] = value;
    } else if (!literal && BOOLEAN_FLAGS.has(token)) {
      const key = ({ "--json": "json", "--yes": "yes", "-y": "yes", "--dry-run": "dryRun", "--check": "check", "--open": "open", "--help": "help", "-h": "help", "--version": "version", "-V": "version", "--no-nfet": "noNfet", "--once": "once" })[token];
      flags[key] = true;
    } else if (!literal && token.startsWith("-")) {
      throw Object.assign(new Error(`unknown flag ${token}`), { exitCode: 2 });
    } else words.push(token);
  }
  flags.cwd = resolve(String(flags.cwd));
  const integerFlag = (name, value, fallback, min, max) => {
    if (value == null) return fallback;
    const raw = String(value);
    if (!/^\d+$/.test(raw)) throw Object.assign(new Error(`${name} requires a whole number from ${min} to ${max}`), { exitCode: 2 });
    const parsed = Number(raw);
    if (!Number.isSafeInteger(parsed) || parsed < min || parsed > max) {
      throw Object.assign(new Error(`${name} requires a whole number from ${min} to ${max}`), { exitCode: 2 });
    }
    return parsed;
  };
  flags.timeout = integerFlag("--timeout", flags.timeout, undefined, 1_000, 3_600_000);
  flags.maxSteps = integerFlag("--max-steps", flags.maxSteps, 12, 1, 40);
  if (flags.permissionMode && !PERMISSION_MODES.includes(flags.permissionMode)) throw Object.assign(new Error(`--mode must be one of: ${PERMISSION_MODES.join(", ")}`), { exitCode: 2 });
  return { flags, words };
}

const HELP = `${wordmark()} — local intelligence, under your control  ${ui.dim(`v${VERSION}`)}

${ui.bold("USE IT NATURALLY")}
  lolm                                      interactive terminal
  lolm "answer this question…"              automatic routing
  lolm "make me a PDF and save it on my Desktop"
  lolm "code an HTML page here"
  lolm "update yourself"

${ui.bold("COMMANDS")}
  chat                         interactive terminal UI
  agent                        interactive autonomous agent UI
  run <task>                   run one autonomous task and return
  ask <question>               answer with read-only file/web tools
  code <task>                  inspect, edit, run, and verify locally
  pdf <request> --out FILE     create a real local PDF
  html <request> --out FILE    create a self-contained HTML file
  setup [provider]             configure any provider/API key
  providers                    list built-in and custom providers
  models                       list live models for the selected provider
  nfet status|test             inspect or exercise the real NFET monitor
  doctor                       verify provider, key, model, and NFET runtime
  tools [group]                list typed tools, schemas, and risk classes
  tools inspect NAME           inspect one tool contract
  plugins                      list enabled local tool plugins
  mcp list|doctor              inspect or connect configured MCP servers
  runs                         list durable local agent runs
  run show|resume RUN_ID       inspect or resume a durable run
  config show|set|unset        manage ~/.lolm/config.json
  request get <path>           read-only raw provider API escape hatch
  update [--check]             update the npm CLI in place

${ui.bold("GLOBAL OPTIONS")}
  --provider NAME    OpenAI, Anthropic, Gemini, xAI, OpenRouter, Groq,
                     Mistral, DeepSeek, Together, Cerebras, Ollama, custom
  --model NAME       any model exposed by the provider
  --api-key KEY      one-off key (environment variables are safer)
  --base-url URL     custom OpenAI-compatible endpoint
  --cwd DIR          working directory for local tools
  --yes              approve requested file writes and commands
  --mode MODE        readonly, standard, developer, or trusted
  --dry-run          preview writes and commands
  --json             stable machine-readable output
  --once             answer once and return to the shell
  --no-nfet          explicitly run without the local NFET monitor

Flags override environment, then config, then defaults. Keys are never printed. Run ${ui.cyan("lolm setup")} first.`;

const CONSOLE_HELP = `Just describe the outcome you want. Examples:

  Make a PDF comparing local and cloud agents and put it on my Desktop
  Fix the failing tests in this project
  Build a polished HTML page here
  Explain this error and tell me what to do next
  Try again

Conversation controls: /clear · /provider NAME · /model NAME · /cwd PATH · /mode MODE · /debug · /exit`;

function emit(flags, payload, human = "") {
  if (flags.json) process.stdout.write(`${JSON.stringify(payload)}\n`);
  else if (human) process.stdout.write(`${human}\n`);
}

function taskRoute(text) {
  const value = String(text || "").trim();
  const compoundWork = /\b(then|test|tests|script|repository|project|deploy|publish|run (?:it|the|a)|multiple files|and verify|and check)\b/i.test(value);
  const namedFileWork = /\b(?:make|create|write|build|implement|modify|change|repair|fix|edit)\b/i.test(value)
    && /(?:^|[\s'"`])(?:\.\.?\/|~\/)?[a-z0-9_.-]+\.[a-z0-9]{1,10}\b/i.test(value);
  if (isRetryPhrase(value)) return "retry";
  if (/\b(update|upgrade)\s+(yourself|lolm|the cli)\b/i.test(value)) return "update";
  if (/\b(pdf)\b/i.test(value) && /\b(make|create|write|generate|build|turn|convert)\b/i.test(value)) return "pdf";
  if (!compoundWork && /\b(html|web\s?page|landing page|website)\b/i.test(value) && /\b(make|create|code|build|write|design)\b/i.test(value)) return "html";
  if (namedFileWork || /\b(code|implement|fix|debug|refactor|edit|file|script|app|component|test)\b/i.test(value)) return "code";
  return "ask";
}

function inferredOut(task, kind, cwd) {
  const lower = task.toLowerCase();
  let root = cwd;
  if (/\bdesktop\b/.test(lower)) root = join(homedir(), "Desktop");
  else if (/\bdownloads?\b/.test(lower)) root = join(homedir(), "Downloads");
  else if (/\bdocuments?\b/.test(lower)) root = join(homedir(), "Documents");
  const explicit = task.match(/(?:save|put|write|export)(?:\s+it)?\s+(?:to|at|as)\s+([~/.][^\s"']*\.(?:pdf|html?))/i)?.[1];
  if (explicit) return resolve(explicit.replace(/^~/, homedir()));
  const named = task.match(/(?:named|called|file(?:\s+named)?|as)\s+["'`]?([a-z0-9_.-]+\.(?:pdf|html?))/i)?.[1]
    || task.match(/\b([a-z0-9_.-]+\.(?:pdf|html?))\b/i)?.[1];
  if (named) return resolve(root, named);
  return join(root, kind === "pdf" ? "lolm-document.pdf" : "lolm-page.html");
}

async function openLocal(path) {
  const command = process.platform === "darwin" ? "open" : process.platform === "win32" ? "cmd" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", path] : [path];
  return new Promise((resolvePromise) => {
    const child = spawn(command, args, { stdio: "ignore", detached: true });
    child.once("error", () => resolvePromise(false));
    child.once("spawn", () => { child.unref(); resolvePromise(true); });
  });
}

async function setup(config, flags, words) {
  let provider = normalizeProvider(flags.provider || words[1] || "");
  if (!provider && process.stdin.isTTY) {
    process.stdout.write(`${Object.entries(PROVIDERS).map(([id, value]) => `  ${ui.cyan(id.padEnd(12))} ${value.label}`).join("\n")}\n`);
    provider = normalizeProvider(await askPrompt("Provider", config.provider || "openai"));
  }
  provider ||= "openai";
  if (!PROVIDERS[provider]) throw Object.assign(new Error(`unknown provider '${provider}'`), { exitCode: 2 });
  const spec = PROVIDERS[provider];
  const prior = config.providers?.[provider] || {};
  const model = flags.model || (process.stdin.isTTY ? await askPrompt("Model", prior.model || spec.model) : prior.model || spec.model);
  const baseUrl = flags.baseUrl || (provider === "custom" && process.stdin.isTTY ? await askPrompt("OpenAI-compatible base URL", prior.baseUrl || "http://127.0.0.1:8000/v1") : prior.baseUrl || spec.baseUrl);
  let apiKey = flags.apiKey || prior.apiKey || "";
  if (!spec.noKey && !apiKey && process.stdin.isTTY) {
    const backend = nativeSecretBackend();
    apiKey = await secretPrompt(`${spec.label} API key (${backend ? `saved in ${backend}` : "saved in protected local config"}; Enter to use env only)`);
    if (apiKey === null) {
      emit(flags, { ok: false, cancelled: true, provider }, `${ui.dim("Setup cancelled. No configuration was changed.")}`);
      return config;
    }
  }
  const environmentKey = (spec.env || []).find((name) => process.env[name]);
  const candidateKey = apiKey || (environmentKey ? process.env[environmentKey] : "");
  if (!spec.noKey && !candidateKey) throw Object.assign(new Error(`${spec.label} needs an API key. Enter one, set ${spec.env?.[0] || "the provider environment variable"}, or pass --api-key for this setup.`), { exitCode: 2, code: "MISSING_API_KEY" });
  const draftProvider = { ...prior, model, baseUrl, ...(candidateKey ? { apiKey: candidateKey } : {}) };
  const draft = { ...config, provider, providers: { ...(config.providers || {}), [provider]: draftProvider } };
  const runtime = resolveRuntime(draft, { ...flags, apiKey: candidateKey });
  const models = await spinner(`Validating ${spec.label}`, () => listModels(runtime), { enabled: !flags.json });
  if (models.length && !models.includes(model)) {
    throw Object.assign(new Error(`${spec.label} accepted the credential, but model '${model}' was not returned. Available examples: ${models.slice(0, 8).join(", ")}`), { code: "MODEL_NOT_AVAILABLE" });
  }
  let secret = { stored: false, backend: null, reference: null };
  if (apiKey) secret = await storeProviderSecret(provider, apiKey);
  const savedProvider = { ...prior, model, baseUrl };
  if (secret.stored) savedProvider.apiKeyRef = secret.reference;
  else if (apiKey) savedProvider.apiKey = apiKey;
  else if (prior.apiKeyRef) savedProvider.apiKeyRef = prior.apiKeyRef;
  const next = { ...config, provider, providers: { ...(config.providers || {}), [provider]: savedProvider } };
  await saveConfig(next);
  emit(flags, { ok: true, provider, model, base_url: baseUrl, key_stored: Boolean(apiKey), key_backend: secret.backend || (apiKey ? "protected config (0600)" : environmentKey ? `env:${environmentKey}` : "not-required"), validated: true, models_visible: models.length, config: CONFIG_PATH },
    `${successText("Configured and verified")} ${spec.label} · ${model}\n${ui.dim(secret.backend ? `Credential: ${secret.backend}` : apiKey ? "Credential: protected local config (0600)" : environmentKey ? `Credential: ${environmentKey}` : "No API key required")}\n${ui.dim(CONFIG_PATH)}`);
  return next;
}

function successText(text) { return ui.green(`✓ ${text}`); }

async function configCommand(config, flags, words) {
  const action = words[1] || "show";
  if (action === "show") {
    const runtime = resolveRuntime(config, flags);
    return emit(flags, { ok: true, config_path: CONFIG_PATH, runtime: publicRuntime(runtime), nfet: await inspectNfet(config) },
      JSON.stringify({ config: CONFIG_PATH, ...publicRuntime(runtime), nfet: await inspectNfet(config) }, null, 2));
  }
  const key = words[2], value = words.slice(3).join(" ");
  if (!key || (action === "set" && !value)) throw Object.assign(new Error("usage: lolm config set <provider|model|base-url|api-key|nfet|nfet-profile|nfet-device|nfet-checkpoint> <value>"), { exitCode: 2 });
  const provider = normalizeProvider(flags.provider || config.provider || "ollama");
  const next = structuredClone(config);
  next.providers ||= {}; next.providers[provider] ||= {};
  const target = {
    provider: [next, "provider"], model: [next.providers[provider], "model"], "base-url": [next.providers[provider], "baseUrl"],
    "api-key": [next.providers[provider], "apiKey"], nfet: [next.nfet ||= {}, "enabled"],
    "nfet-profile": [next.nfet ||= {}, "profile"], "nfet-device": [next.nfet ||= {}, "device"],
    "nfet-checkpoint": [next.nfet ||= {}, "checkpoint"], "nfet-home": [next.nfet ||= {}, "home"],
  }[key];
  if (!target) throw Object.assign(new Error(`unknown config key '${key}'`), { exitCode: 2 });
  if (action === "unset") delete target[0][target[1]];
  else if (action === "set") target[0][target[1]] = key === "provider" ? normalizeProvider(value) : key === "nfet" ? !/^(off|false|0)$/i.test(value) : value;
  else throw Object.assign(new Error("config action must be show, set, or unset"), { exitCode: 2 });
  await saveConfig(next);
  emit(flags, { ok: true, action, key, config: CONFIG_PATH }, `${successText("Saved")} ${key}`);
  return next;
}

async function doctor(config, flags) {
  const runtime = resolveRuntime(config, flags);
  const nfet = await inspectNfet(config);
  const checks = await collectDiagnostics({ cwd: flags.cwd, configPath: CONFIG_PATH, runtime, nfet });
  if (!runtime.keyRequired || runtime.apiKey) {
    try {
      const models = await spinner(`Contacting ${runtime.label}`, () => listModels(runtime), { enabled: !flags.json });
      const selectedVisible = !models.length || models.includes(runtime.model);
      checks.push({ name: "Provider API", ok: true, detail: `${models.length} models visible` });
      checks.push({ name: "Selected model", ok: selectedVisible,
        detail: selectedVisible ? runtime.model : `${runtime.model} not returned; run 'lolm models'` });
    } catch (error) { checks.push({ name: "Provider API", ok: false, detail: error.message }); }
  }
  const ok = checks.every((item) => item.ok || item.optional);
  const actions = checks.filter((item) => !item.ok && item.action).map((item) => item.action);
  emit(flags, { ok, runtime: publicRuntime(runtime), nfet, checks, actions }, `${checks.map((item) => `${item.ok ? ui.green("✓") : item.optional ? ui.amber("!") : ui.red("×")} ${item.name.padEnd(18)} ${ui.dim(item.detail)}${item.optional && !item.ok ? ui.dim(" · optional") : ""}`).join("\n")}${actions.length ? `\n\n${ui.bold("Recommended actions")}\n${actions.map((action) => `  ${ui.cyan("→")} ${action}`).join("\n")}` : ""}`);
  return ok ? 0 : 1;
}

async function toolsCommand(flags, words) {
  const toolbox = createAgentToolbox({ cwd: flags.cwd, mode: "readonly" });
  try {
    if (words[1] === "inspect") {
      const name = words[2];
      if (!name) throw Object.assign(new Error("usage: lolm tools inspect <tool-name>"), { exitCode: 2 });
      const tool = toolbox.registry.resolve(name);
      if (!tool) throw Object.assign(new Error(`unknown tool '${name}'`), { exitCode: 2 });
      const { execute, classify, ...publicTool } = tool;
      return emit(flags, { ok: true, tool: publicTool }, `${ui.bold(publicTool.name)}  ${ui.dim(`[${publicTool.risk}]`)}\n${publicTool.description}\n\n${JSON.stringify(publicTool.inputSchema, null, 2)}`);
    }
    const group = words[1] || undefined;
    const tools = toolbox.registry.list({ group });
    if (group && !tools.length) throw Object.assign(new Error(`unknown or empty tool group '${group}'`), { exitCode: 2 });
    const groups = Object.groupBy ? Object.groupBy(tools, (tool) => tool.name.split(".")[0]) : tools.reduce((out, tool) => { (out[tool.name.split(".")[0]] ||= []).push(tool); return out; }, {});
    const human = Object.entries(groups).map(([name, rows]) => `${ui.bold(name)} ${ui.dim(`(${rows.length})`)}\n${rows.map((tool) => `  ${ui.cyan(tool.name.padEnd(24))} ${ui.dim(tool.risk.padEnd(8))} ${tool.description}`).join("\n")}`).join("\n\n");
    return emit(flags, { ok: true, count: tools.length, tools }, human);
  } finally { await toolbox.close(); }
}

async function extensionsCommand(command, flags, words) {
  const toolbox = createAgentToolbox({ cwd: flags.cwd, mode: "readonly" });
  try {
    if (command === "plugins") {
      const plugins = await toolbox.plugins.discover();
      return emit(flags, { ok: true, plugins }, plugins.length ? plugins.map((plugin) => `${plugin.enabled ? ui.green("●") : ui.dim("○")} ${plugin.name || "invalid plugin"} ${ui.dim(plugin.version || "")}  ${plugin.manifest_path}${plugin.error ? `\n  ${ui.red(plugin.error)}` : ""}`).join("\n") : ui.dim("No plugins found. Add an enabled lolm-plugin.json under ~/.lolm/plugins or .lolm/plugins."));
    }
    const action = words[1] || "list";
    const config = await readMcpConfig(flags.cwd);
    if (action === "list") {
      const servers = Object.entries(config.mcpServers || {}).map(([name, spec]) => ({ name, enabled: spec.enabled === true, command: spec.command, args: spec.args || [] }));
      return emit(flags, { ok: true, servers }, servers.length ? servers.map((server) => `${server.enabled ? ui.green("●") : ui.dim("○")} ${ui.cyan(server.name.padEnd(20))} ${server.command} ${server.args.join(" ")}`).join("\n") : ui.dim("No MCP servers configured."));
    }
    if (action === "doctor") {
      const status = await toolbox.mcp.connectEnabled({ includeDisabled: true });
      const ok = status.every((server) => server.connected);
      return emit(flags, { ok, servers: status }, status.map((server) => `${server.connected ? ui.green("✓") : ui.red("×")} ${server.name}  ${server.connected ? `${server.tools.length} tools` : server.error || "not connected"}`).join("\n"));
    }
    throw Object.assign(new Error("usage: lolm mcp list|doctor"), { exitCode: 2 });
  } finally { await toolbox.close(); }
}

function runStore() {
  const root = process.env.LOLM_RUNS_DIR || (process.env.LOLM_LAST_TASK ? join(dirname(process.env.LOLM_LAST_TASK), "runs") : undefined);
  return new RunStore(root ? { root } : undefined);
}

async function runsCommand(flags, words) {
  const store = runStore();
  const action = words[1];
  if (!action) {
    const runs = await store.list({ limit: 50 });
    return emit(flags, { ok: true, runs }, runs.length ? runs.map((run) => `${ui.cyan(run.id)}  ${String(run.status).padEnd(10)} ${ui.dim(run.created_at)}  ${String(run.prompt || "").slice(0, 80)}`).join("\n") : ui.dim("No local runs yet."));
  }
  if (!["show", "resume"].includes(action) || !words[2]) throw Object.assign(new Error("usage: lolm run show|resume <run-id>"), { exitCode: 2 });
  if (action === "show") {
    const run = await store.show(words[2]);
    return emit(flags, { ok: true, run }, `${ui.bold(run.meta.id)}  ${run.meta.status}\n${ui.dim(`${run.meta.created_at} · ${run.meta.cwd}`)}\n\n${run.events.map((event) => `${event.at}  ${event.type}`).join("\n")}`);
  }
  return null;
}

async function updateSelf(flags) {
  const latest = await new Promise((resolvePromise, reject) => {
    const child = spawn("npm", ["view", "lolm-cli", "version", "--json"], { stdio: ["ignore", "pipe", "pipe"] });
    let out = "", err = "";
    child.stdout.on("data", (c) => out += c); child.stderr.on("data", (c) => err += c);
    child.on("exit", (code) => code === 0 ? resolvePromise(String(JSON.parse(out)).trim()) : reject(new Error(err.trim() || "npm update check failed")));
  });
  const numbers = (value) => String(value).replace(/^v/, "").split(/[.-]/).slice(0, 3).map((part) => Number(part) || 0);
  const [currentParts, latestParts] = [numbers(VERSION), numbers(latest)];
  const newer = latestParts.some((part, index) => part > currentParts[index] && latestParts.slice(0, index).every((prior, i) => prior === currentParts[i]));
  if (flags.check || !newer) {
    emit(flags, { ok: true, current: VERSION, latest, update_available: newer }, newer ? `Update available: ${VERSION} → ${latest}` : `${successText("Up to date")} lolm ${VERSION}${latest !== VERSION ? ui.dim(` · registry ${latest}`) : ""}`);
    return 0;
  }
  if (!flags.yes && !await confirm(`Update lolm ${VERSION} → ${latest}?`, true)) return 0;
  const code = await new Promise((resolvePromise) => {
    const child = spawn("npm", ["install", "-g", "lolm-cli@latest"], { stdio: flags.json ? "ignore" : "inherit" });
    child.on("exit", (value) => resolvePromise(value ?? 1));
  });
  if (code) throw new Error(`npm install exited ${code}`);
  emit(flags, { ok: true, previous: VERSION, current: latest }, `${successText("Updated")} lolm ${latest}`);
  return 0;
}

function monitorFor(config, flags, surface = null) {
  if (flags.noNfet) return null;
  return new NfetMonitor(config, { onStatus: (message) => {
    if (flags.json) return;
    if (!surface) return note(message);
    if (/^loading/i.test(message)) surface.progress({ thinking: true });
    else surface.tool("Local NFET quality controller ready");
  } });
}

async function executeTask(command, text, config, flags, sharedMonitor = null, history = [], surface = null) {
  const runtime = resolveRuntime(config, flags);
  const store = runStore();
  const run = flags.resumeRunId
    ? (await store.resume(flags.resumeRunId)).meta
    : await store.create({ command, prompt: text, cwd: flags.cwd, mode: flags.permissionMode || (flags.yes ? "developer" : "standard"), provider: runtime.provider, model: runtime.model });
  const persistEvent = store.eventSink(run.id);
  const eventSink = async (event) => { await persistEvent(event); surface?.activity(event); };
  const monitor = sharedMonitor || monitorFor(config, flags, surface);
  const resolvedOut = ["pdf", "html"].includes(command)
    ? resolve(flags.out || inferredOut(text, command, flags.cwd)) : "";
  const taskRecord = { command, prompt: text, cwd: flags.cwd, out: resolvedOut, status: "running", run_id: run.id };
  await saveLastTask(taskRecord).catch(() => {});
  const onNfet = (result) => {
    void eventSink({ type: "nfet.visible", available: Boolean(result?.available), decision: result?.decision || null, telemetry: result?.telemetry || null }).catch(() => {});
    if (flags.json) return;
    if (surface) surface.nfet(result);
    else process.stderr.write(`  ${nfetLine(result)}\n`);
  };
  const onPhase = ({ label, step, maxSteps }) => {
    void eventSink({ type: "agent.phase", label, step, max_steps: maxSteps }).catch(() => {});
    if (flags.json) return;
    const customerLabel = command === "pdf" && label === "Thinking" ? "Building your document"
      : command === "html" && label === "Thinking" ? "Designing your page"
        : label === "Thinking" ? "Working on it" : label === "Continuing" ? "Improving the result" : label;
    const detail = step ? `${step}/${maxSteps}` : `${runtime.label} · ${runtime.model}`;
    if (surface) surface.phase(customerLabel, detail);
    else section(label, detail);
  };
  const onTool = (label) => {
    void eventSink({ type: "agent.activity", label }).catch(() => {});
    if (flags.json) return;
    if (surface) surface.tool(label);
    else note(label);
  };
  const onProgress = (progress) => { if (!flags.json && surface) surface.progress(progress); };
  // Warm the trained NFET model while the provider works. The first request no
  // longer pays those two startup costs serially, and a shared interactive
  // monitor remains hot for the rest of the conversation.
  const deterministicGreeting = command === "ask"
    && /^(hi|hey|hello|yo|good (morning|afternoon|evening))[!.?\s]*$/i.test(text.trim());
  if (monitor && !deterministicGreeting) void monitor.start().catch(() => {});
  try {
    if (command === "pdf") {
      const out = resolvedOut;
      if (await access(out).then(() => true).catch(() => false) && !flags.yes && !await confirm(`Replace ${out}?`)) return 0;
      const generated = await generateDocument({
        prompt: text,
        runtime,
        monitor,
        cwd: flags.cwd,
        maxSteps: Math.min(flags.maxSteps, 8),
        history,
        onPhase,
        onTool,
        onNfet,
        onProgress,
      });
      if (!generated.text) throw new Error("The provider returned an empty document.");
      const result = await createPdf(generated.text, out, { title: "" });
      if (flags.open) await openLocal(result.path);
      const payload = { ok: true, run_id: run.id, kind: "pdf", ...result, provider: runtime.provider, model: runtime.model, nfet: generated.nfet,
        response: `Created the PDF at ${result.path}.` };
      if (typeof flags.captureResult === "function") flags.captureResult(payload);
      if (surface) {
        surface.success("PDF created");
        surface.assistant(`${result.path}\n\n${result.pages} page${result.pages === 1 ? "" : "s"} · ${result.bytes} bytes`);
      } else {
        emit(flags, payload, `${successText("Created PDF")}\n${result.path}\n${ui.dim(`${result.pages} page${result.pages === 1 ? "" : "s"} · ${result.bytes} bytes`)}`);
      }
      await saveLastTask({ ...taskRecord, status: "complete", result_path: result.path }).catch(() => {});
      await store.finish(run.id, "completed", { kind: "pdf", result_path: result.path });
      return 0;
    }
    if (command === "html") {
      const out = resolvedOut;
      if (await access(out).then(() => true).catch(() => false) && !flags.yes && !await confirm(`Replace ${out}?`)) return 0;
      const generated = await generateHtml({ prompt: text, runtime, monitor, onPhase, onNfet, onProgress });
      if (!/^<!doctype html>|<html[\s>]/i.test(generated.html)) throw new Error("The provider did not return a complete HTML document.");
      await mkdir(dirname(out), { recursive: true });
      await writeFile(out, `${generated.html}\n`);
      if (flags.open) await openLocal(out);
      const payload = { ok: true, run_id: run.id, kind: "html", path: out, bytes: Buffer.byteLength(generated.html), provider: runtime.provider, model: runtime.model, nfet: generated.nfet,
        response: `Created the HTML page at ${out}.` };
      if (typeof flags.captureResult === "function") flags.captureResult(payload);
      if (surface) { surface.success("HTML page created"); surface.assistant(out); }
      else emit(flags, payload, `${successText("Created HTML")}\n${out}`);
      await saveLastTask({ ...taskRecord, status: "complete", result_path: out }).catch(() => {});
      await store.finish(run.id, "completed", { kind: "html", result_path: out });
      return 0;
    }
    const result = await runAgent({ prompt: text, mode: command, runtime, monitor, cwd: flags.cwd, yes: flags.yes, dryRun: flags.dryRun, maxSteps: flags.maxSteps, history, onPhase, onTool, onNfet, onProgress, permissionMode: flags.permissionMode, eventSink });
    result.run_id = run.id;
    if (typeof flags.captureResult === "function") flags.captureResult(result);
    if (surface) surface.assistant(result.response || result.error);
    else emit(flags, result, renderMarkdown(result.response || result.error));
    await saveLastTask({ ...taskRecord, status: result.ok ? "complete" : "incomplete", error: result.error }).catch(() => {});
    await store.finish(run.id, result.ok ? "completed" : "incomplete", { verified: result.verified, error: result.error || null, steps: result.steps });
    return result.ok ? 0 : 1;
  } catch (error) {
    error.retryAvailable = true;
    await saveLastTask({ ...taskRecord, status: "failed", error: error.message }).catch(() => {});
    await store.finish(run.id, "failed", { error: error.message, code: error.code || "TASK_FAILED" }).catch(() => {});
    throw error;
  } finally { if (!sharedMonitor) await monitor?.close(); }
}

async function interactive(config, flags, { seed = null } = {}) {
  let runtime = resolveRuntime(config, flags);
  const info = await inspectNfet(config);
  const surface = createConsoleSurface({
    version: VERSION,
    provider: runtime.label,
    model: runtime.model,
    nfet: info.available && info.enabled ? "NFET active" : "NFET setup needed",
    mode: flags.permissionMode || (flags.yes ? "developer" : "standard"),
    workspace: flags.cwd,
  });
  surface.open();
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout, historySize: 500 });
  const monitor = monitorFor(config, flags, surface);
  let history = [];
  let queued = seed;
  try {
    while (true) {
      let line, seededCommand = "";
      if (queued) {
        line = String(queued.text || "").trim();
        seededCommand = queued.command || "";
        queued = null;
        surface.user(line);
      } else {
        try { line = (await rl.question(`\n${ui.indigo("╭─ YOU")}\n${ui.violet("╰─›")} `)).trim(); }
        catch { break; }
      }
      if (!line) continue;
      if (["/exit", "/quit"].includes(line)) break;
      if (line === "/help") { surface.assistant(CONSOLE_HELP); continue; }
      if (line === "/clear") { history = []; process.stdout.write("\x1b[2J\x1b[H"); surface.success("Conversation cleared"); continue; }
      if (line === "/debug") { surface.setVerbose(!surface.verbose); surface.success(`NFET details ${surface.verbose ? "shown" : "hidden"}`); continue; }
      if (line.startsWith("/provider ")) { flags.provider = normalizeProvider(line.slice(10)); runtime = resolveRuntime(config, flags); surface.success(`${runtime.label} selected`); continue; }
      if (line.startsWith("/model ")) { flags.model = line.slice(7).trim(); runtime = resolveRuntime(config, flags); surface.success(`${runtime.model} selected`); continue; }
      if (line.startsWith("/cwd ")) { flags.cwd = resolve(line.slice(5).trim()); surface.success(`Working directory: ${flags.cwd}`); continue; }
      if (line.startsWith("/mode ")) {
        const mode = line.slice(6).trim().toLowerCase();
        if (!PERMISSION_MODES.includes(mode)) surface.error(`Mode must be one of: ${PERMISSION_MODES.join(", ")}`);
        else { flags.permissionMode = mode; surface.success(`${mode} permission mode selected`); }
        continue;
      }
      try {
        let command = seededCommand || taskRoute(line);
        let taskText = line;
        if (command === "retry") {
          const previous = await loadLastTask();
          if (!previous) {
            surface.error("There isn’t an unfinished or recent task to retry.");
            continue;
          }
          command = previous.command;
          taskText = previous.prompt;
          if (previous.cwd) flags.cwd = resolve(previous.cwd);
          if (previous.out) flags.out = previous.out;
          surface.phase("Resuming your last request", command === "pdf" ? "PDF" : command);
        }
        let captured = null;
        flags.captureResult = (value) => { captured = value; };
        const code = command === "update" ? await updateSelf(flags) : await executeTask(command, taskText, config, flags, monitor, history, surface);
        if (code) surface.warning("I couldn’t finish that cleanly. You can say “try again”.");
        if (captured?.response) {
          history.push({ role: "user", content: taskText }, { role: "assistant", content: captured.response });
          history = history.slice(-20);
        }
      } catch (error) {
        surface.error(error.message, { retry: Boolean(error.retryAvailable) });
      } finally {
        delete flags.captureResult;
      }
    }
  } finally { rl.close(); await monitor?.close(); surface.close(); }
  return 0;
}

async function main() {
  const { flags, words } = parse(process.argv.slice(2));
  if (flags.version) return emit(flags, { ok: true, version: VERSION }, VERSION);
  if (flags.help) return emit(flags, { ok: true, version: VERSION, commands: ["chat", "agent", "run", "ask", "code", "pdf", "html", "setup", "providers", "models", "nfet", "doctor", "tools", "plugins", "mcp", "runs", "config", "request", "update"] }, HELP);
  let config = await loadConfig();
  if (!words.length) return process.stdin.isTTY ? interactive(config, flags) : emit(flags, { ok: true, help: true }, HELP);
  let command = words[0].toLowerCase();
  const known = new Set(["chat", "agent", "run", "runs", "ask", "code", "pdf", "html", "setup", "providers", "models", "nfet", "doctor", "tools", "plugins", "mcp", "config", "request", "update", "help"]);
  let text = words.slice(1).join(" ").trim();
  if (!known.has(command)) { text = words.join(" "); command = taskRoute(text); }
  if (command === "help") return emit(flags, { ok: true, help: true }, HELP);
  if (["chat", "agent"].includes(command)) return interactive(config, flags);
  if (command === "tools") return toolsCommand(flags, words);
  if (["plugins", "mcp"].includes(command)) return extensionsCommand(command, flags, words);
  if (command === "runs") return runsCommand(flags, ["run"]);
  if (command === "run" && words[1] === "show") return runsCommand(flags, words);
  if (command === "run" && words[1] === "resume") {
    if (!words[2]) throw Object.assign(new Error("usage: lolm run resume <run-id>"), { exitCode: 2 });
    const prior = await runStore().show(words[2]);
    flags.resumeRunId = prior.meta.id;
    flags.cwd = resolve(prior.meta.cwd || flags.cwd);
    flags.permissionMode = prior.meta.mode || flags.permissionMode;
    flags.provider ||= prior.meta.provider;
    flags.model ||= prior.meta.model;
    text = prior.meta.prompt;
    command = prior.meta.command || taskRoute(text);
    flags.once = true;
  } else if (command === "run") {
    text = words.slice(1).join(" ").trim();
    if (!text) throw Object.assign(new Error("run requires a task"), { exitCode: 2 });
    command = taskRoute(text);
    flags.once = true;
  }
  if (command === "setup") { config = await setup(config, flags, words); return 0; }
  if (command === "config") { await configCommand(config, flags, words); return 0; }
  if (command === "providers") {
    const rows = Object.entries(PROVIDERS).map(([id, value]) => ({ id, label: value.label, protocol: value.protocol, env: value.env, default_model: value.model, selected: normalizeProvider(config.provider) === id }));
    return emit(flags, { ok: true, providers: rows }, rows.map((row) => `${row.selected ? ui.green("●") : ui.dim("○")} ${ui.cyan(row.id.padEnd(12))} ${row.label.padEnd(25)} ${ui.dim(row.default_model || "set your model")}`).join("\n"));
  }
  if (command === "models") {
    const runtime = resolveRuntime(config, flags);
    const models = await spinner(`Loading ${runtime.label} models`, () => listModels(runtime), { enabled: !flags.json });
    return emit(flags, { ok: true, provider: runtime.provider, models }, models.join("\n"));
  }
  if (command === "request") {
    if (words[1]?.toLowerCase() !== "get" || !words[2]) throw Object.assign(new Error("usage: lolm request get /provider/path"), { exitCode: 2 });
    const runtime = resolveRuntime(config, flags);
    const result = await rawGet(runtime, words[2]);
    return emit(flags, { ok: true, provider: runtime.provider, path: words[2], result }, JSON.stringify(result, null, 2));
  }
  if (command === "doctor") return doctor(config, flags);
  if (command === "update") return updateSelf(flags);
  if (command === "nfet") {
    const action = words[1] || "status", info = await inspectNfet(config);
    if (action === "status") return emit(flags, { ok: info.available, nfet: info }, JSON.stringify(info, null, 2));
    if (action === "test") {
      const monitor = monitorFor(config, flags);
      try {
        const result = await monitor.decide(words.slice(2).join(" ") || "LOLM NFET local monitor test", { reset: true, checkpoint: "result", verified: true });
        return emit(flags, { ok: result.available, nfet: result }, nfetLine(result));
      } finally { await monitor?.close(); }
    }
    throw Object.assign(new Error("usage: lolm nfet status|test [text]"), { exitCode: 2 });
  }
  if (command === "retry") {
    const previous = await loadLastTask();
    if (!previous) throw Object.assign(new Error("There isn’t a recent LOLM task to retry."), { exitCode: 2 });
    command = previous.command;
    text = previous.prompt;
    if (previous.cwd) flags.cwd = resolve(previous.cwd);
    if (previous.out && !flags.out) flags.out = previous.out;
  }
  if (!text) throw Object.assign(new Error(`${command} requires a task or question`), { exitCode: 2 });
  if (process.stdin.isTTY && !flags.json && !flags.once && ["ask", "code", "pdf", "html"].includes(command)) {
    return interactive(config, flags, { seed: { command, text } });
  }
  return executeTask(command, text, config, flags);
}

function handleFailure(error) {
  const json = process.argv.includes("--json");
  const exitCode = error.exitCode || 1;
  const payload = { ok: false, exit_code: exitCode, error: { code: error.code || (error instanceof ProviderError ? error.code : "CLI_ERROR"), message: error.message } };
  if (json) process.stdout.write(`${JSON.stringify(payload)}\n`);
  else failure(error.message);
  process.exitCode = exitCode;
}

void main().then((code) => {
  if (Number.isInteger(code)) process.exitCode = code;
}).catch(handleFailure);
