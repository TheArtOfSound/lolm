#!/usr/bin/env node
// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** LOLM: local, open-source, BYOK agent with real NFET control. */
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
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
import { banner, confirm, createConsoleSurface, failure, nfetLine, note, prompt as askPrompt, renderMarkdown, secretPrompt, section, spinner, success, ui, warning, wordmark } from "../lib/tui.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
const VERSION = pkg.version;

const VALUE_FLAGS = new Set(["--provider", "--model", "--api-key", "--base-url", "--cwd", "--out", "-o", "--timeout", "--max-steps"]);
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
      const key = ({ "--provider": "provider", "--model": "model", "--api-key": "apiKey", "--base-url": "baseUrl", "--cwd": "cwd", "--out": "out", "-o": "out", "--timeout": "timeout", "--max-steps": "maxSteps" })[token];
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
  ask <question>               answer with read-only file/web tools
  code <task>                  inspect, edit, run, and verify locally
  pdf <request> --out FILE     create a real local PDF
  html <request> --out FILE    create a self-contained HTML file
  setup [provider]             configure any provider/API key
  providers                    list built-in and custom providers
  models                       list live models for the selected provider
  nfet status|test             inspect or exercise the real NFET monitor
  doctor                       verify provider, key, model, and NFET runtime
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

Conversation controls: /clear · /provider NAME · /model NAME · /cwd PATH · /debug · /exit`;

function emit(flags, payload, human = "") {
  if (flags.json) process.stdout.write(`${JSON.stringify(payload)}\n`);
  else if (human) process.stdout.write(`${human}\n`);
}

function taskRoute(text) {
  const value = String(text || "").trim();
  if (isRetryPhrase(value)) return "retry";
  if (/\b(update|upgrade)\s+(yourself|lolm|the cli)\b/i.test(value)) return "update";
  if (/\b(pdf)\b/i.test(value) && /\b(make|create|write|generate|build|turn|convert)\b/i.test(value)) return "pdf";
  if (/\b(html|web\s?page|landing page|website)\b/i.test(value) && /\b(make|create|code|build|write|design)\b/i.test(value)) return "html";
  if (/\b(code|implement|fix|debug|refactor|edit|file|script|app|component|test)\b/i.test(value)) return "code";
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
  if (!spec.noKey && !apiKey && process.stdin.isTTY) apiKey = await secretPrompt(`${spec.label} API key (stored locally with mode 0600; Enter to use env only)`);
  const next = { ...config, provider, providers: { ...(config.providers || {}), [provider]: { ...prior, model, baseUrl, ...(apiKey ? { apiKey } : {}) } } };
  await saveConfig(next);
  emit(flags, { ok: true, provider, model, base_url: baseUrl, key_stored: Boolean(apiKey), config: CONFIG_PATH },
    `${successText("Configured")} ${spec.label} · ${model}\n${ui.dim(CONFIG_PATH)}\nRun ${ui.cyan("lolm doctor")} to verify it.`);
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
  const checks = [
    { name: "Node.js", ok: Number(process.versions.node.split(".")[0]) >= 20, detail: process.version },
    { name: "Provider", ok: true, detail: `${runtime.label} · ${runtime.model}` },
    { name: "API key", ok: !runtime.keyRequired || Boolean(runtime.apiKey), detail: runtime.keySource },
    { name: "NFET source", ok: Boolean(nfet.home), detail: nfet.home || "set LOLM_HOME to a cloned LOLM repo" },
    { name: "NFET checkpoint", ok: nfet.checkpoint_available, detail: nfet.checkpoint },
  ];
  if (!runtime.keyRequired || runtime.apiKey) {
    try {
      const models = await spinner(`Contacting ${runtime.label}`, () => listModels(runtime), { enabled: !flags.json });
      const selectedVisible = !models.length || models.includes(runtime.model);
      checks.push({ name: "Provider API", ok: true, detail: `${models.length} models visible` });
      checks.push({ name: "Selected model", ok: selectedVisible,
        detail: selectedVisible ? runtime.model : `${runtime.model} not returned; run 'lolm models'` });
    } catch (error) { checks.push({ name: "Provider API", ok: false, detail: error.message }); }
  }
  const ok = checks.every((item) => item.ok);
  emit(flags, { ok, runtime: publicRuntime(runtime), nfet, checks }, checks.map((item) => `${item.ok ? ui.green("✓") : ui.red("×")} ${item.name.padEnd(16)} ${ui.dim(item.detail)}`).join("\n"));
  return ok ? 0 : 1;
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
  const monitor = sharedMonitor || monitorFor(config, flags, surface);
  const resolvedOut = ["pdf", "html"].includes(command)
    ? resolve(flags.out || inferredOut(text, command, flags.cwd)) : "";
  const taskRecord = { command, prompt: text, cwd: flags.cwd, out: resolvedOut, status: "running" };
  await saveLastTask(taskRecord).catch(() => {});
  const onNfet = (result) => {
    if (flags.json) return;
    if (surface) surface.nfet(result);
    else process.stderr.write(`  ${nfetLine(result)}\n`);
  };
  const onPhase = ({ label, step, maxSteps }) => {
    if (flags.json) return;
    const customerLabel = command === "pdf" && label === "Thinking" ? "Building your document"
      : command === "html" && label === "Thinking" ? "Designing your page"
        : label === "Thinking" ? "Working on it" : label === "Continuing" ? "Improving the result" : label;
    const detail = step ? `${step}/${maxSteps}` : `${runtime.label} · ${runtime.model}`;
    if (surface) surface.phase(customerLabel, detail);
    else section(label, detail);
  };
  const onTool = (label) => {
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
      const payload = { ok: true, kind: "pdf", ...result, provider: runtime.provider, model: runtime.model, nfet: generated.nfet,
        response: `Created the PDF at ${result.path}.` };
      if (typeof flags.captureResult === "function") flags.captureResult(payload);
      if (surface) {
        surface.success("PDF created");
        surface.assistant(`${result.path}\n\n${result.pages} page${result.pages === 1 ? "" : "s"} · ${result.bytes} bytes`);
      } else {
        emit(flags, payload, `${successText("Created PDF")}\n${result.path}\n${ui.dim(`${result.pages} page${result.pages === 1 ? "" : "s"} · ${result.bytes} bytes`)}`);
      }
      await saveLastTask({ ...taskRecord, status: "complete", result_path: result.path }).catch(() => {});
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
      const payload = { ok: true, kind: "html", path: out, bytes: Buffer.byteLength(generated.html), provider: runtime.provider, model: runtime.model, nfet: generated.nfet,
        response: `Created the HTML page at ${out}.` };
      if (typeof flags.captureResult === "function") flags.captureResult(payload);
      if (surface) { surface.success("HTML page created"); surface.assistant(out); }
      else emit(flags, payload, `${successText("Created HTML")}\n${out}`);
      await saveLastTask({ ...taskRecord, status: "complete", result_path: out }).catch(() => {});
      return 0;
    }
    const result = await runAgent({ prompt: text, mode: command, runtime, monitor, cwd: flags.cwd, yes: flags.yes, dryRun: flags.dryRun, maxSteps: flags.maxSteps, history, onPhase, onTool, onNfet, onProgress });
    if (typeof flags.captureResult === "function") flags.captureResult(result);
    if (surface) surface.assistant(result.response || result.error);
    else emit(flags, result, renderMarkdown(result.response || result.error));
    await saveLastTask({ ...taskRecord, status: result.ok ? "complete" : "incomplete", error: result.error }).catch(() => {});
    return result.ok ? 0 : 1;
  } catch (error) {
    error.retryAvailable = true;
    await saveLastTask({ ...taskRecord, status: "failed", error: error.message }).catch(() => {});
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
        try { line = (await rl.question(`\n${ui.indigo("YOU")} ${ui.violet("›")} `)).trim(); }
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
  if (flags.help) return emit(flags, { ok: true, version: VERSION, commands: ["chat", "ask", "code", "pdf", "html", "setup", "providers", "models", "nfet", "doctor", "config", "request", "update"] }, HELP);
  let config = await loadConfig();
  if (!words.length) return process.stdin.isTTY ? interactive(config, flags) : emit(flags, { ok: true, help: true }, HELP);
  let command = words[0].toLowerCase();
  const known = new Set(["chat", "ask", "code", "pdf", "html", "setup", "providers", "models", "nfet", "doctor", "config", "request", "update", "help"]);
  let text = words.slice(1).join(" ").trim();
  if (!known.has(command)) { text = words.join(" "); command = taskRoute(text); }
  if (command === "help") return emit(flags, { ok: true, help: true }, HELP);
  if (command === "chat") return interactive(config, flags);
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

try {
  const code = await main();
  if (Number.isInteger(code)) process.exitCode = code;
} catch (error) {
  const json = process.argv.includes("--json");
  const exitCode = error.exitCode || 1;
  const payload = { ok: false, exit_code: exitCode, error: { code: error.code || (error instanceof ProviderError ? error.code : "CLI_ERROR"), message: error.message } };
  if (json) process.stdout.write(`${JSON.stringify(payload)}\n`);
  else failure(error.message);
  process.exitCode = exitCode;
}
