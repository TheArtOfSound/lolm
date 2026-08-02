#!/usr/bin/env node
// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * lolm — control console for the LOLM agent.
 *
 * Fail-closed shipping, path-contained --save, independent receipt verification,
 * artifact install from sealed manifest, task-state inspect, doctor.
 */

import { writeFile, mkdir, readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, join, resolve, isAbsolute } from "node:path";
import { homedir } from "node:os";
import process from "node:process";
import {
  runAgent, runCode, buildVisual, listCodeReceipts, getStatus,
  getMemory, rememberFact, forgetMemory, friendly, AgentRunError,
  authHeaders,
} from "lolm-nfet-client";
import { safeDestination } from "../lib/paths.mjs";
import { evaluateShipped, evaluateAskOk } from "../lib/shipped.mjs";
import { verifyCodeReceipt } from "../lib/receipt.mjs";
import { installVerifiedArtifacts, installVerifiedFile, validateManifest } from "../lib/artifacts.mjs";
import { safeTerminal } from "../lib/terminal.mjs";

const VERSION = "0.3.0-beta.1";
const DEFAULT_BASE = "https://lolm.imagineqira.com";
const CONFIG_PATH = process.env.LOLM_CONFIG || join(homedir(), ".lolm", "cli.json");

// ── output ───────────────────────────────────────────────────────────────────

const useColor =
  process.stdout.isTTY && !process.env.NO_COLOR && process.env.TERM !== "dumb";
const c = (code) => (s) => (useColor ? `\x1b[${code}m${s}\x1b[0m` : String(s));
const dim = c("2"), bold = c("1"), red = c("31"), green = c("32");
const yellow = c("33"), blue = c("34"), magenta = c("35"), cyan = c("36");

let JSON_MODE = process.argv.slice(2).includes("--json");
let BROKEN_PIPE = false;
const write = (stream, value, newline = true) => {
  if (BROKEN_PIPE) return;
  const raw = String(value ?? "") + (newline ? "\n" : "");
  stream.write(JSON_MODE ? raw : safeTerminal(raw));
};
const out = (s = "") => { write(process.stdout, s); };
const err = (s = "") => { write(process.stderr, s); };
const log = (s = "") => { if (!JSON_MODE) err(s); };
const emit = (obj) => { write(process.stdout, JSON.stringify(obj)); };

class CliError extends Error {
  constructor(message, { exitCode = 1, code = "CLI_ERROR", details = null } = {}) {
    super(message);
    this.name = "CliError";
    this.exitCode = exitCode;
    this.code = code;
    this.details = details;
  }
}

function fail(msg, code = 1, errorCode = code === 2 ? "USAGE_ERROR" : "CLI_ERROR") {
  throw new CliError(msg, { exitCode: code, code: errorCode });
}

const COMMAND_ABORT = new AbortController();
let SIGNAL_EXIT = 0;
for (const [signal, code] of [["SIGINT", 130], ["SIGTERM", 143]]) {
  process.once(signal, () => {
    SIGNAL_EXIT = code;
    COMMAND_ABORT.abort(new DOMException(`${signal} received`, "AbortError"));
  });
}
for (const stream of [process.stdout, process.stderr]) {
  stream.on("error", (error) => {
    if (error?.code === "EPIPE") {
      BROKEN_PIPE = true;
      COMMAND_ABORT.abort(error);
      process.exitCode = 0;
      return;
    }
    throw error;
  });
}

// ── config / identity ────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    const raw = await readFile(CONFIG_PATH, "utf8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function saveConfig(cfg) {
  const dir = dirname(CONFIG_PATH);
  await mkdir(dir, { recursive: true });
  await writeFile(CONFIG_PATH, JSON.stringify(cfg, null, 2) + "\n", { mode: 0o600 });
}

function clientOpts(flags) {
  return {
    baseUrl: flags.base,
    apiKey: flags.apiKey || process.env.LOLM_API_KEY || "",
    license: flags.license || process.env.LOLM_LICENSE || "",
    timeoutMs: flags.timeout,
    idleTimeoutMs: flags.idleTimeout,
    signal: COMMAND_ABORT.signal,
  };
}

async function apiGet(path, flags) {
  const base = flags.base.replace(/\/+$/, "");
  const url = new URL(path, base.endsWith("/") ? base : base + "/");
  // fix relative
  const full = path.startsWith("http") ? path : `${base}${path.startsWith("/") ? "" : "/"}${path}`;
  const timeoutSignal = AbortSignal.timeout(flags.timeout);
  const signal = AbortSignal.any([COMMAND_ABORT.signal, timeoutSignal]);
  const r = await fetch(full, {
    headers: authHeaders({
      apiKey: flags.apiKey || process.env.LOLM_API_KEY,
      license: flags.license || process.env.LOLM_LICENSE,
    }),
    signal,
  });
  const advertised = Number(r.headers.get("content-length") || 0);
  const maxBytes = 5 * 1024 * 1024;
  if (advertised > maxBytes) throw new AgentRunError("JSON response exceeds size limit", {
    status: r.status, code: "RESPONSE_TOO_LARGE",
  });
  const reader = r.body?.getReader();
  const chunks = [];
  let total = 0;
  if (reader) {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > maxBytes) {
          await reader.cancel("response too large");
          throw new AgentRunError("JSON response exceeds size limit", {
            status: r.status, code: "RESPONSE_TOO_LARGE",
          });
        }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
  }
  const body = Buffer.concat(chunks.map((chunk) => Buffer.from(chunk)), total).toString("utf8");
  let j = {};
  try { j = body ? JSON.parse(body) : {}; }
  catch { throw new AgentRunError("malformed JSON response", {
    status: r.status, body: body.slice(0, 200), code: "MALFORMED_RESPONSE",
  }); }
  if (!r.ok) throw new AgentRunError(j.error || `HTTP ${r.status}`, { status: r.status, body: j });
  return j;
}

// ── args ─────────────────────────────────────────────────────────────────────

const FLAG_DEFS = {
  "--json": ["json", "boolean"], "--quiet": ["quiet", "boolean"], "-q": ["quiet", "boolean"],
  "--help": ["help", "boolean"], "-h": ["help", "boolean"],
  "--version": ["version", "boolean"], "-V": ["version", "boolean"],
  "--all": ["all", "boolean"],
  "--yes": ["yes", "boolean"], "-y": ["yes", "boolean"],
  "--fetch": ["fetch", "boolean"], "--stdout": ["stdout", "boolean"],
  "--base": ["base", "value"], "--timeout": ["timeout", "value"],
  "--idle-timeout": ["idleTimeout", "value"], "--save": ["save", "value"],
  "--out": ["out", "value"], "-o": ["out", "value"],
  "--limit": ["limit", "value"], "--max-steps": ["maxSteps", "value"],
  "--id": ["id", "value"], "--api-key": ["apiKey", "value"],
  "--license": ["license", "value"], "--fail-on": ["failOn", "value"],
  "--receipt": ["receipt", "value"], "--conversation": ["conversation", "value"],
};

const COMMON = ["json", "help", "base", "timeout", "apiKey", "license"];
const COMMAND_FLAGS = {
  status: COMMON,
  doctor: COMMON,
  ask: [...COMMON, "quiet", "idleTimeout", "failOn"],
  code: [...COMMON, "quiet", "idleTimeout", "save", "receipt", "maxSteps", "conversation"],
  build: [...COMMON, "out", "stdout"],
  receipts: [...COMMON, "limit"],
  receipt: [...COMMON, "fetch"],
  memory: [...COMMON, "all", "id"],
  inspect: [...COMMON, "id", "conversation"],
  config: ["json", "help"],
  whoami: ["json", "help"],
  help: ["help"],
};

function strictInteger(raw, name, min, max) {
  if (!/^[0-9]+$/.test(String(raw))) fail(`${name} must be an integer between ${min} and ${max}`, 2);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    fail(`${name} must be an integer between ${min} and ${max}`, 2);
  }
  return value;
}

function normalizeBase(raw) {
  let url;
  try { url = new URL(String(raw)); } catch { fail("--base must be a valid URL", 2); }
  if (url.username || url.password || url.search || url.hash) {
    fail("--base must not contain credentials, query, or fragment", 2);
  }
  if (url.pathname !== "/") fail("--base must be an origin without a path", 2);
  const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
  if (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) {
    fail("--base requires HTTPS (HTTP is allowed only for loopback)", 2);
  }
  return url.origin;
}

function parseArgs(argv) {
  const flags = {
    base: process.env.LOLM_BASE_URL || DEFAULT_BASE,
    apiKey: process.env.LOLM_API_KEY || "",
    license: process.env.LOLM_LICENSE || "",
    timeout: 120_000,
    idleTimeout: 30_000,
  };
  if (!argv.length) return { flags, rest: [] };
  let cmd = null;
  let allowed = null;
  const prefixedKeys = [];
  const positionals = [];
  let literal = false;
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (!cmd && token === "--") fail("expected a command before --", 2);
    if (cmd && !literal && token === "--") { literal = true; continue; }
    if (!literal && token.startsWith("-")) {
      const def = FLAG_DEFS[token];
      if (!def) fail(`unknown flag ${token}${cmd ? ` for ${cmd}` : ""}`, 2);
      const [key, kind] = def;
      if (cmd && !allowed.has(key)) fail(`unknown flag ${token} for ${cmd}`, 2);
      if (!cmd) prefixedKeys.push([key, token]);
      if (kind === "boolean") {
        flags[key] = true;
        if (key === "json") JSON_MODE = true;
        continue;
      }
      const value = argv[i + 1];
      if (value == null || value === "--" || value.startsWith("-")) {
        fail(`${token} requires a value`, 2);
      }
      flags[key] = value;
      i++;
      continue;
    }
    if (!cmd) {
      cmd = token;
      allowed = new Set(COMMAND_FLAGS[cmd] || ["help"]);
      for (const [key, original] of prefixedKeys) {
        if (!["help", "version", "json"].includes(key) && !allowed.has(key)) {
          fail(`unknown flag ${original} for ${cmd}`, 2);
        }
      }
      continue;
    }
    positionals.push(token);
  }
  flags.timeout = strictInteger(flags.timeout, "--timeout", 1, 3_600_000);
  flags.idleTimeout = strictInteger(flags.idleTimeout, "--idle-timeout", 1, 600_000);
  if (flags.maxSteps != null) flags.maxSteps = strictInteger(flags.maxSteps, "--max-steps", 1, 50);
  if (flags.limit != null) flags.limit = strictInteger(flags.limit, "--limit", 1, 100);
  flags.base = normalizeBase(flags.base);
  if (!cmd && !flags.help && !flags.version) fail("expected a command", 2);
  return { flags, rest: cmd ? [cmd, ...positionals] : [] };
}

const START = `${bold("lolm")} control console  ${dim("v" + VERSION)}

${bold("Next — pick one:")}
  ${cyan("lolm doctor")}
  ${cyan("lolm status")}
  ${cyan('lolm code "write fizzbuzz to 20 in solution.py and run it" --save ./out')}
  ${cyan('lolm ask "what is a sealed receipt?" --fail-on red')}
  ${cyan("lolm receipt verify ./run.receipt.json")}

Web app: ${dim("https://lolm.imagineqira.com/app.html")}
`;

const HELP = `${bold("lolm")} — LOLM control console  ${dim("v" + VERSION)}

${bold("USAGE")}
  lolm <command> [args] [flags]

${bold("COMMANDS")}
  code <task...>        Agentic coding loop (jail). Fail-closed ship gate.
  ask <question...>     Agent answer + control stream. --fail-on red exits 1.
  build <app...>        Visual HTML app build.
  last                  Session intent ledger (last ask/run/artifact/checkpoint).
  retry [--yes]         Retry last failed/code run (session referent).
  resume [--yes]        Resume terminated run from last checkpoint pointer.
  receipts              Recent sealed code receipts.
  receipt verify <file> Local hash + Ed25519 signature verification.
  status                API / model status + usage when available.
  doctor                Connectivity + safety self-check.
  config                Show/set local CLI config (~/.lolm/cli.json).
  whoami                Show identity headers the CLI will send.
  inspect task [--conversation ID | --id task_id]
                        Persistent task state z_t (goals, plan, criteria).
  memory list|add|forget

${bold("FLAGS")}
  --base <url>          API base (default ${DEFAULT_BASE} or $LOLM_BASE_URL)
  --save <dir>          code: install artifacts under <dir> (path-contained)
  --out, -o <file>      build output path
  --api-key <key>       X-LOLM-Api-Key ($LOLM_API_KEY)
  --license <tok>       X-LOLM-License ($LOLM_LICENSE)
  --fail-on red         ask: exit nonzero on red/incomplete proof
  --receipt <path>      write raw receipt JSON after code
  --max-steps <n>       code step cap
  --yes                 confirm retry/resume without interactive prompt
  --json                machine-readable stdout
  --quiet, -q           less progress

${bold("SAFETY")}
  --save installs only a complete, signed, hash-bound manifest into a new directory.
  shipped requires matching done/receipt IDs and every explicit verification gate.
  Network calls have deadlines; terminal output removes control sequences.
`;

// ── commands ─────────────────────────────────────────────────────────────────

async function cmdDoctor(flags) {
  const checks = [];
  const push = (name, ok, detail) => checks.push({ name, ok, detail });

  push("node", true, `v${process.versions.node}`);
  push("cli", true, VERSION);

  // path safety unit
  try {
    safeDestination("/tmp/out", "ok/file.py");
    let threw = false;
    try { safeDestination("/tmp/out", "../../etc/passwd"); } catch { threw = true; }
    push("path_containment", threw, threw ? "rejects .. escape" : "FAILED to reject escape");
  } catch (e) {
    push("path_containment", false, e.message);
  }

  // shipped fail-closed unit
  const bad = evaluateShipped({ ok: true }, { verdict: "broken", ok: false, syntax_ok: true });
  push("shipped_fail_closed", !bad.shipped, bad.shipped ? "BROKEN allows ship" : "broken never ships");

  // network
  try {
    const s = await getStatus({ baseUrl: flags.base, ...clientOpts(flags) });
    push("api_status", true, `model_ready=${s.model_ready} base=${flags.base}`);
  } catch (e) {
    push("api_status", false, e.message);
  }

  try {
    await apiGet("/api/demo/billing/usage", flags);
    push("usage", true, "billing/usage reachable");
  } catch (e) {
    push("usage", false, e.message);
  }

  const ok = checks.every((c) => c.ok);
  if (JSON_MODE) { emit({ ok, checks, config: CONFIG_PATH }); return ok ? 0 : 1; }
  out(`${bold("lolm doctor")} ${ok ? green("PASS") : red("ISSUES")}`);
  for (const c of checks) {
    out(`  ${c.ok ? green("✓") : red("✗")} ${c.name.padEnd(20)} ${dim(c.detail)}`);
  }
  out(dim(`config  ${CONFIG_PATH}`));
  return ok ? 0 : 1;
}

async function cmdConfig(sub, args, flags) {
  const cfg = await loadConfig();
  if (!sub || sub === "show") {
    if (JSON_MODE) return emit({ path: CONFIG_PATH, config: cfg });
    out(dim(CONFIG_PATH));
    out(JSON.stringify(cfg, null, 2));
    return 0;
  }
  if (sub === "set") {
    const [key, ...rest] = args;
    if (!key || !rest.length) fail("usage: lolm config set <key> <value>", 2);
    cfg[key] = rest.join(" ");
    await saveConfig(cfg);
    if (JSON_MODE) return emit({ ok: true, config: cfg });
    out(green("saved") + ` ${key}`);
    return 0;
  }
  if (sub === "path") {
    out(CONFIG_PATH);
    return 0;
  }
  fail("usage: lolm config [show|set|path]", 2);
}

async function cmdWhoami(flags) {
  const cfg = await loadConfig();
  const info = {
    base: flags.base || cfg.base || DEFAULT_BASE,
    apiKey_set: !!(flags.apiKey || process.env.LOLM_API_KEY || cfg.apiKey),
    license_set: !!(flags.license || process.env.LOLM_LICENSE || cfg.license),
    config: CONFIG_PATH,
  };
  if (JSON_MODE) return emit(info);
  out(`${bold("base")}     ${info.base}`);
  out(`${bold("api-key")}  ${info.apiKey_set ? green("set") : dim("unset")}`);
  out(`${bold("license")}  ${info.license_set ? green("set") : dim("unset")}`);
  return 0;
}

async function cmdStatus(flags) {
  const s = await getStatus({ baseUrl: flags.base, ...clientOpts(flags) });
  let usage = null;
  try { usage = await apiGet("/api/demo/billing/usage", flags); } catch { /* optional */ }
  if (JSON_MODE) return emit({ ...s, usage });
  out(`${bold("model")}     ${s.model_ready ? green("ready") : yellow("not ready")}` +
      `${s.busy ? dim("  (busy)") : ""}`);
  out(`${bold("runs")}      ${s.runs_completed}/${s.runs_started} completed` +
      (s.last_run_seconds != null ? dim(`  last ${s.last_run_seconds}s`) : ""));
  out(`${bold("replays")}   ${s.replays}`);
  const L = s.limits || {};
  if (L.reasoner) out(`${bold("reasoner")}  ${L.reasoner}`);
  if (usage && !usage.unlimited) {
    const r = usage.runs || {};
    out(`${bold("quota")}     ${r.remaining ?? "?"}/${r.limit ?? "?"} runs left` +
        (r.topup ? dim(` (+${r.topup} top-up)`) : "") +
        dim(` · tier ${usage.tier || "?"}`));
  } else if (usage?.unlimited) {
    out(`${bold("quota")}     unlimited`);
  }
}

async function receiptPublicKeys(flags) {
  const response = await apiGet("/api/demo/receipts/keys", flags);
  return Object.fromEntries((response.keys || []).filter((key) =>
    key.alg === "Ed25519" && key.key_id && key.public_key
  ).map((key) => [key.key_id, key.public_key]));
}

async function persistLocalSessionFromReceipt(task, done, receipt, flags = {}) {
  /** Write hosted run events into ~/.lolm/sessions so last/retry/resume work offline. */
  try {
    const dir = sessionDir();
    await mkdir(dir, { recursive: true });
    const sidRaw = receipt?.session_id || flags.conversation || done?.run_id || receipt?.run_id || `local_${Date.now()}`;
    // Sanitize like the Python ledger (opaque / hashed)
    let sid = String(sidRaw).replace(/[^A-Za-z0-9_.-]/g, "");
    if (!sid || sid.includes("..") || sid.startsWith(".")) {
      const { createHash } = await import("node:crypto");
      sid = "sess_" + createHash("sha256").update(String(sidRaw)).digest("hex").slice(0, 16);
    }
    const path = join(dir, `${sid}.json`);
    let prev = {};
    try { prev = JSON.parse(await readFile(path, "utf8")); } catch { /* new */ }
    const status = receipt?.verdict || (receipt?.ok ? "shipped" : "incomplete");
    const resume = receipt?.resume_package || prev.resume_package || null;
    const next = {
      ...prev,
      session_id: sid,
      last_code_run_id: receipt?.run_id || done?.run_id || prev.last_code_run_id || "",
      last_run_task: task || prev.last_run_task || "",
      last_run_status: status,
      last_failed_run_id: receipt?.ok ? (prev.last_failed_run_id || "") : (receipt?.run_id || done?.run_id || ""),
      last_checkpoint_id: resume?.checkpoint_id || receipt?.last_known_green?.checkpoint_id || prev.last_checkpoint_id || "",
      resume_token: resume?.resume_token || prev.resume_token || "",
      workspace_snapshot: resume?.workspace_snapshot || prev.workspace_snapshot || {},
      reliability_snapshot: resume?.reliability_snapshot || prev.reliability_snapshot || {},
      failure_ledger: resume?.failure_ledger || prev.failure_ledger || {},
      contract_snapshot: resume?.contract_snapshot || prev.contract_snapshot || {},
      checkpoint_payload: resume?.checkpoint_payload || prev.checkpoint_payload || {},
      artifact_ids: receipt?.files || done?.files || prev.artifact_ids || [],
      updated_ts: Date.now() / 1000,
      history: [
        ...((prev.history || []).slice(-49)),
        { kind: "code_run", run_id: receipt?.run_id || done?.run_id, task: String(task || "").slice(0, 300), status, ts: Date.now() / 1000 },
      ],
    };
    await writeFile(path, JSON.stringify(next, null, 2), "utf8");
    return next;
  } catch {
    return null;
  }
}

async function cmdCode(task, flags) {
  let lastStep = -1;
  let manifest = null;
  let sessionLedger = null;
  const opts = clientOpts(flags);
  const resumePackage = flags.resumePackage || null;

  const result = await runCode({
    task,
    baseUrl: flags.base,
    maxSteps: flags.maxSteps,
    apiKey: opts.apiKey,
    license: opts.license,
    conversationId: flags.conversation || "",
    resumePackage: resumePackage || undefined,
    resumeToken: flags.resumeToken || resumePackage?.resume_token || undefined,
    onEvent(ev) {
      const d = ev.data || {};
      if (ev.event === "artifact_manifest") manifest = d;
      if (ev.event === "session_ledger") sessionLedger = d;
      if (JSON_MODE) { if (!flags.quiet) err(dim(ev.event)); return; }
      switch (ev.event) {
        case "code_start":
          log(dim(`sandbox ${d.sandbox}`));
          break;
        case "code_thinking":
          if (!flags.quiet && d.step !== lastStep) {
            lastStep = d.step;
            log(dim(`\n· step ${d.step + 1}/${d.of}`));
          }
          break;
        case "file_changed":
          if (!flags.quiet) log(`  ${cyan("write")}  ${d.path} ${dim(`(${d.bytes}b)`)}` +
                          (d.edit ? dim(" [edit]") : ""));
          break;
        case "artifact_manifest":
          if (!flags.quiet) log(`  ${green("manifest")} ${ (d.files||[]).length } file(s) · id ${dim((d.artifact_id||"").slice(0,12))}`);
          break;
        case "command_started":
          if (!flags.quiet) log(`  ${blue("run")}    ${d.command}` +
                          (d.verify ? dim(" [verify]") : ""));
          break;
        case "command_finished": {
          if (flags.quiet) break;
          const ok = d.exit_code === 0 && !d.blocked;
          const tag = ok ? green("exit 0") : red(`exit ${d.exit_code ?? "?"}`);
          log(`         ${tag}` + (d.blocked ? red(" blocked") : ""));
          const body = ((d.stdout || "") + (d.stderr || "")).trim();
          if (body) {
            for (const l of body.split("\n").slice(-6)) log(dim("         │ ") + l);
          }
          break;
        }
        case "agent_note":
          if (!flags.quiet && d.text) log(`  ${magenta("note")}   ${d.text}`);
          break;
        case "error":
          err(red("  stream error: ") + (d.error || "unknown"));
          break;
      }
    },
  });

  // runCode returns { done, receipt }
  const done = result?.done || result || {};
  // Never mutate the sealed receipt object — hash/signature must verify as shipped.
  const r = result?.receipt || done.receipt || {};
  // Session transport is a sibling event, not part of the receipt seal
  const sessionForLedger = sessionLedger || {
    session_id: r.session_id,
    resume_package: r.resume_package,
  };
  // Persist hosted run into local session ledger for last/retry/resume
  await persistLocalSessionFromReceipt(task, done, {
    ...r,
    session_id: sessionForLedger.session_id || r.session_id,
    resume_package: sessionForLedger.resume_package || r.resume_package,
  }, flags);
  let publicKeys = {};
  try { publicKeys = await receiptPublicKeys(flags); } catch { /* fail closed below */ }
  // Verify a clean receipt (strip any client-only fields if a buggy server added them)
  const rForVerify = { ...r };
  delete rForVerify.resume_package;
  delete rForVerify.session_id;
  let integrity = verifyCodeReceipt(rForVerify, { publicKeys });
  if (!integrity?.integrity?.verified && (r.resume_package || r.session_id)) {
    // Keep original attempt recorded; ship gate uses stripped verification
  } else if (integrity?.integrity?.verified) {
    // prefer stripped verify when it matches
  }
  // If stripped verifies and raw does not, use stripped for the gate
  const integrityRaw = verifyCodeReceipt(r, { publicKeys });
  if (!integrityRaw?.integrity?.verified && integrity?.receipt_hash_match) {
    /* keep integrity from stripped */
  } else if (integrityRaw?.integrity?.verified) {
    integrity = integrityRaw;
  }
  let manifestBound = false;
  if (manifest) {
    try {
      validateManifest(manifest);
      manifestBound = r.run_id === manifest.run_id
        && r.verification?.artifact_manifest_sha256 === manifest.manifest_sha256;
    } catch { manifestBound = false; }
  }
  let gate = evaluateShipped(done, r, { receiptVerified: integrity.integrity.verified });

  if (flags.receipt) {
    const rp = isAbsolute(flags.receipt) ? flags.receipt : resolve(process.cwd(), flags.receipt);
    await mkdir(dirname(rp), { recursive: true });
    await writeFile(rp, JSON.stringify({ done, receipt: r, integrity }, null, 2), "utf8");
  }

  let saved = null;
  if (flags.save) {
    if (!gate.shipped) {
      saved = { requested: true, committed: false, verified: false,
        error: "run receipt is not verified and shippable" };
    } else if (!manifestBound) {
      saved = { requested: true, committed: false, verified: false,
        error: "artifact manifest is missing, malformed, or not bound to the receipt" };
    } else {
      saved = await installVerifiedArtifacts(flags.save, manifest);
    }
    done.saved = saved;
  }
  gate = evaluateShipped(done, r, {
    receiptVerified: integrity.integrity.verified,
    saveRequested: !!flags.save,
    artifactsVerified: !!saved?.verified,
  });
  const { shipped, reasons } = gate;

  if (JSON_MODE) {
    emit({
      ok: shipped,
      schema: "lolm.cli.result.v2",
      exit_code: shipped ? 0 : 1,
      shipped,
      reasons,
      integrity,
      done,
      receipt: r,
      saved,
    });
    return shipped ? 0 : 1;
  }

  out("");
  out(`${bold("verdict")}   ${shipped ? green(r.verdict || "shipped") : red(r.verdict || "incomplete")}`);
  if (!shipped && reasons.length) out(`${bold("why")}       ${dim(reasons.join("; "))}`);
  if (done.summary) out(`${bold("summary")}   ${done.summary}`);
  if (r.files?.length) out(`${bold("files")}     ${r.files.join(", ")}`);
  if (r.syntax_ok === false && r.syntax_error) {
    out(`${bold("syntax")}    ${red("does not compile")} ${dim(r.syntax_error.split("\n").pop())}`);
  }
  const runs = [r.green_runs, r.failed_runs].some((v) => v != null)
    ? `${r.green_runs ?? 0} green / ${r.failed_runs ?? 0} failed` : null;
  if (runs) out(`${bold("runs")}      ${runs}`);
  if (r.receipt_sha) {
    const tag = integrity.receipt_hash_match === true ? green("hash ok")
      : integrity.receipt_hash_match === false ? red("hash mismatch")
      : yellow("hash n/a");
    out(`${bold("receipt")}   ${dim(r.receipt_sha)}  ${tag}`);
  }
  if (r.task_state?.task_id) {
    out(`${bold("task")}      ${r.task_state.task_id} ${dim(`(open criteria: ${(r.task_state.open_criteria||[]).length})`)}`);
  }
  if (saved) {
    if (saved.committed) out(`\n${green("saved")} ${saved.files.length} verified file(s) → ${saved.destination}`);
    else err(red("  not saved: ") + saved.error);
  }
  return shipped ? 0 : 1;
}

async function cmdAsk(question, flags) {
  let printed = false;
  const res = await runAgent({
    command: question,
    baseUrl: flags.base,
    ...clientOpts(flags),
    onToken(t) {
      if (JSON_MODE) return;
      if (t.channel === "final" || t.channel === "draft") {
        write(process.stdout, t.token, false); printed = true;
      }
    },
    onEvent(ev) {
      if (JSON_MODE || flags.quiet) return;
      const line = friendly(ev);
      if (line) err(dim("  · ") + line);
    },
  });

  const failOn = (flags.failOn || "").toLowerCase();
  let gate = { ok: true, reasons: [] };
  if (failOn === "red" || failOn === "any") {
    gate = evaluateAskOk(res);
  }

  if (JSON_MODE) {
    emit({ ok: gate.ok, result: res, gate });
    return gate.ok ? 0 : 1;
  }
  if (printed) out("");
  const p = res.proof || {};
  if (!flags.quiet && p.plain) out("\n" + dim(p.plain));
  const counts = Object.entries(p.control_counts || {})
    .filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join("  ");
  if (counts) out(dim(`decisions  ${counts}`));
  if (!gate.ok) {
    err(red("ask failed gate: ") + gate.reasons.join("; "));
    return 1;
  }
  return 0;
}

async function cmdBuild(task, flags) {
  const dest = flags.out || "lolm-app.html";
  log(dim("building… (a real headless-browser check runs server-side)"));
  const res = await buildVisual({ task, baseUrl: flags.base, ...clientOpts(flags) });
  let publicKeys = {};
  try { publicKeys = await receiptPublicKeys(flags); } catch { /* fail closed below */ }
  const integrity = verifyCodeReceipt(res.receipt, { publicKeys });
  const htmlBytes = Buffer.from(String(res.html || ""), "utf8");
  const expected = res.receipt?.verification?.html_sha256 || "";
  const actual = createHash("sha256").update(htmlBytes).digest("hex");
  const contentVerified = integrity.integrity.verified
    && res.verified === true
    && expected === actual
    && res.receipt?.verification?.byte_count === htmlBytes.length;
  if (!contentVerified) {
    throw new CliError("visual receipt or HTML hash verification failed", {
      code: "RECEIPT_VERIFICATION_FAILED", exitCode: 1,
    });
  }
  if (flags.stdout) {
    if (JSON_MODE) fail("--stdout and --json cannot be combined", 2);
    if (process.stdout.isTTY) fail("--stdout requires redirected output", 2);
    write(process.stdout, res.html, false);
    return 0;
  }
  const p = isAbsolute(dest) ? dest : resolve(process.cwd(), dest);
  const saved = await installVerifiedFile(p, htmlBytes, expected);
  if (JSON_MODE) {
    emit({ schema: "lolm.cli.result.v2", ok: true, exit_code: 0,
      path: p, bytes: htmlBytes.length, receipt: integrity, saved });
    return 0;
  }
  out(`${green("built")} ${htmlBytes.length} verified bytes → ${p}`);
  return 0;
}

async function cmdReceipts(flags) {
  const { receipts = [], stats = {} } = await listCodeReceipts({
    baseUrl: flags.base, limit: flags.limit || 10, ...clientOpts(flags),
  });
  if (JSON_MODE) return emit({ receipts, stats });
  if (!receipts.length) { out(dim("no receipts yet")); return 0; }
  for (const r of receipts) {
    const v = r.verdict === "shipped" ? green("shipped")
      : r.verdict === "broken" ? red("broken") : yellow(r.verdict || "?");
    out(`${dim((r.receipt_sha || "").slice(0, 10).padEnd(11))}${v.padEnd(useColor ? 18 : 9)} ` +
        `${(r.task || "").slice(0, 62)}`);
  }
  if (stats.ok != null) out(dim(`\n${stats.ok} ok / ${stats.recent ?? receipts.length} recent`));
  return 0;
}

async function cmdReceiptVerify(target, flags) {
  let receipt;
  if (!target && flags.fetch) fail("receipt verify --fetch needs a receipt id or path", 2);
  if (!target) fail("usage: lolm receipt verify <file.json>", 2);

  if (target.endsWith(".json") || target.includes("/") || target.startsWith(".")) {
    const p = isAbsolute(target) ? target : resolve(process.cwd(), target);
    receipt = JSON.parse(await readFile(p, "utf8"));
    if (receipt.receipt && !receipt.verdict) receipt = receipt.receipt;
  } else {
    const { receipts = [] } = await listCodeReceipts({
      baseUrl: flags.base, limit: 50, ...clientOpts(flags),
    });
    receipt = receipts.find((r) => (r.receipt_sha || "").startsWith(target));
    if (!receipt) fail(`receipt not found in recent ledger: ${target}`, 1);
  }

  // Verification is independent: fetch public material, then verify entirely
  // in-process. The service's own verify endpoint is never an authority.
  let publicKeys = {};
  try { publicKeys = await receiptPublicKeys(flags); } catch { /* env keys may suffice */ }
  const v = verifyCodeReceipt(receipt, { publicKeys });

  if (JSON_MODE) {
    emit(v);
    return v.integrity?.verified ? 0 : 1;
  }
  out(`${bold("receipt verify")}`);
  out(`  schema     ${v.schema_valid ? green("ok") : red("no")}`);
  out(`  hash       ${v.receipt_hash_match === true ? green("match") : v.receipt_hash_match === false ? red("MISMATCH") : yellow("n/a")}`);
  if (v.claimed_sha) out(`  claimed    ${dim(v.claimed_sha)}`);
  if (v.expected_sha) out(`  recomputed ${dim(v.expected_sha)}`);
  const sigLabel = v.signature_valid === true ? green("valid")
    : v.signature_valid === false ? red("INVALID")
    : yellow(receipt.signature ? "unknown public key" : "none");
  out(`  signature  ${sigLabel}${v.signing_key ? dim(" · "+v.signing_key) : ""}`);
  out(`  ledger     ${v.ledger_link_present ? green("linked") : dim("none")}`);
  out(`  verdict    ${v.verdict_consistent ? green("consistent") : red("inconsistent")}`);
  out(`  ship gate  ${v.shipped_allowed ? green("allowed") : yellow("blocked")}`);
  for (const n of v.notes || []) out(dim(`  note       ${n}`));
  out(`  ${v.integrity?.verified ? green("VERIFIED") : red("NOT VERIFIED")}  ${dim(v.verified_at)}  ${dim(v.integrity?.method || "")}`);
  return v.integrity?.verified ? 0 : 1;
}


// ── Session Intent Ledger (local, cross-process referents) ───────────────────

function sessionDir() {
  return process.env.LOLM_SESSION_DIR || join(homedir(), ".lolm", "sessions");
}

async function loadLatestSession() {
  const { readdir, stat } = await import("node:fs/promises");
  const dir = sessionDir();
  let files = [];
  try {
    files = (await readdir(dir)).filter((f) => f.endsWith(".json"));
  } catch {
    return null;
  }
  if (!files.length) return null;
  const ranked = [];
  for (const f of files) {
    try {
      const st = await stat(join(dir, f));
      ranked.push({ f, mtime: st.mtimeMs });
    } catch { /* skip */ }
  }
  ranked.sort((a, b) => b.mtime - a.mtime);
  try {
    const raw = await readFile(join(dir, ranked[0].f), "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** Resolve bare follow-ups the way SessionIntentLedger does server-side. */
function resolveFollowupLocal(text, pointers) {
  const t = String(text || "").trim();
  if (!pointers) {
    return { action: "clarify", prompt: "No session ledger found. Run a code task or ask first." };
  }
  if (/^(try\s+again|retry|again|once\s+more|same\s+as\s+before|redo|re-?run)\s*[.!]?\s*$/i.test(t)) {
    const rid = pointers.last_failed_run_id || pointers.last_code_run_id;
    if (rid) {
      return {
        action: "retry",
        run_id: rid,
        task: pointers.last_run_task,
        checkpoint_id: pointers.last_checkpoint_id,
        status: pointers.last_run_status,
      };
    }
    if (pointers.last_ask) {
      return { action: "retry_ask", ask: pointers.last_ask };
    }
    return { action: "clarify", prompt: "Nothing to retry in session ledger." };
  }
  if (/^(continue|go\s+on|keep\s+going|resume|pick\s+up)\s*[.!]?\s*$/i.test(t)) {
    if (pointers.last_code_run_id && pointers.last_run_status === "terminated") {
      return {
        action: "resume",
        run_id: pointers.last_code_run_id,
        task: pointers.last_run_task,
        checkpoint_id: pointers.last_checkpoint_id,
      };
    }
    return { action: "clarify", prompt: "No terminated run to resume." };
  }
  return { action: "passthrough", text: t };
}

async function cmdLast(flags) {
  const p = await loadLatestSession();
  if (!p) {
    if (JSON_MODE) return emit({ ok: false, error: "no_session" });
    out(dim("no session ledger yet — run `lolm code` or `lolm ask` first"));
    return 0;
  }
  if (JSON_MODE) return emit({ schema: "lolm.session.last.v1", ...p });
  out(`${bold("session")}   ${p.session_id || "?"}`);
  if (p.last_ask) out(`${bold("last ask")}  ${String(p.last_ask).slice(0, 200)}`);
  if (p.last_code_run_id) {
    out(`${bold("last run")}  ${p.last_code_run_id}  ${dim(p.last_run_status || "")}`);
    if (p.last_run_task) out(`${bold("task")}      ${String(p.last_run_task).slice(0, 160)}`);
  }
  if (p.last_failed_run_id) out(`${bold("failed")}    ${p.last_failed_run_id}`);
  if (p.last_checkpoint_id) out(`${bold("checkpoint")} ${p.last_checkpoint_id}`);
  if (p.artifact_ids?.length) out(`${bold("artifacts")} ${(p.artifact_ids || []).slice(-5).join(", ")}`);
  if (p.open_question) out(`${bold("open Q")}    ${String(p.open_question).slice(0, 160)}`);
  if (p.option_set?.length) {
    out(`${bold("options")}`);
    for (let i = 0; i < Math.min(p.option_set.length, 8); i++) {
      out(dim(`  ${i + 1}. `) + p.option_set[i]);
    }
  }
  return 0;
}

async function cmdRetry(args, flags) {
  const p = await loadLatestSession();
  const text = args.join(" ").trim() || "try again";
  const resolved = resolveFollowupLocal(text, p);
  if (resolved.action === "clarify") {
    if (JSON_MODE) return emit({ ok: false, ...resolved });
    out(yellow(resolved.prompt || "cannot resolve retry referent"));
    return 2;
  }
  if (resolved.action === "retry_ask") {
    if (!flags.yes && !JSON_MODE) {
      out(`${bold("retry ask")} ${String(resolved.ask).slice(0, 120)}`);
      out(dim("re-run with: lolm retry --yes   (or lolm ask \"…\")"));
      return 0;
    }
    return await cmdAsk(resolved.ask, flags);
  }
  if (resolved.action === "retry" || resolved.action === "resume") {
    const task = resolved.task;
    if (!task) {
      fail("session has a run id but no task text to retry", 1);
    }
    // Prefer full resume package from session file (workspace + checkpoint)
    let pkg = resolved.resume_package || null;
    if (!pkg && p) {
      pkg = {
        resume_token: p.resume_token || "",
        run_id: p.last_code_run_id || resolved.run_id,
        task: p.last_run_task || task,
        status: p.last_run_status,
        checkpoint_id: p.last_checkpoint_id || resolved.checkpoint_id,
        workspace_snapshot: p.workspace_snapshot || {},
        reliability_snapshot: p.reliability_snapshot || {},
        failure_ledger: p.failure_ledger || {},
        contract_snapshot: p.contract_snapshot || {},
        checkpoint_payload: p.checkpoint_payload || {},
        event_cursor: p.event_cursor || 0,
        session_id: p.session_id,
      };
      if (!Object.keys(pkg.workspace_snapshot || {}).length && !pkg.checkpoint_id) {
        pkg = null;
      }
    }
    if (!flags.yes && !JSON_MODE) {
      out(`${bold(resolved.action)}  run=${resolved.run_id || "?"} status=${resolved.status || "?"}`);
      out(`${bold("task")}   ${String(task).slice(0, 160)}`);
      if (resolved.checkpoint_id) out(`${bold("ckpt")}   ${resolved.checkpoint_id}`);
      if (pkg?.resume_token) out(`${bold("token")}  ${String(pkg.resume_token).slice(0, 48)}`);
      if (pkg?.workspace_snapshot) {
        out(`${bold("files")}  ${Object.keys(pkg.workspace_snapshot).slice(0, 8).join(", ")}`);
      } else {
        out(yellow("warning: no workspace snapshot — will restart task without restored tree"));
      }
      out(dim(`confirm: lolm ${resolved.action} --yes`));
      return 0;
    }
    flags.conversation = flags.conversation || resolved.run_id || p?.session_id || "";
    if (pkg) {
      flags.resumePackage = pkg;
      flags.resumeToken = pkg.resume_token || "";
    }
    return await cmdCode(task, flags);
  }
  if (JSON_MODE) return emit(resolved);
  out(dim(JSON.stringify(resolved)));
  return 0;
}

async function cmdResume(args, flags) {
  // Force resume semantics with full package transport
  const p = await loadLatestSession();
  if (!p?.last_code_run_id) {
    if (JSON_MODE) return emit({ ok: false, error: "no_run" });
    out(yellow("no code run to resume — try `lolm last`"));
    return 2;
  }
  if (p.last_run_status && p.last_run_status !== "terminated" && !flags.yes) {
    out(dim(`last status is "${p.last_run_status}" (not terminated). Use --yes to force resume/retry.`));
  }
  const hasTransport = !!(
    p.resume_token || p.last_checkpoint_id
    || (p.workspace_snapshot && Object.keys(p.workspace_snapshot).length)
  );
  if (!hasTransport) {
    out(yellow("session has no checkpoint/workspace transport — resume would only re-prompt the task."));
    if (!flags.yes) {
      out(dim("re-run after a code receipt that embeds resume_package, or pass --yes to retry task text only."));
      return 2;
    }
  }
  return await cmdRetry(["resume"], { ...flags, yes: flags.yes || false });
}

async function cmdInspect(sub, args, flags) {
  if (sub === "task" || !sub) {
    let path;
    if (flags.id) path = `/api/demo/code/task_state/${encodeURIComponent(flags.id)}`;
    else if (flags.conversation) {
      path = `/api/demo/code/task_state?conversation_id=${encodeURIComponent(flags.conversation)}`;
    } else {
      fail("inspect task needs --id <task_id> or --conversation <id>", 2);
    }
    const j = await apiGet(path, flags);
    if (JSON_MODE) return emit(j);
    const z = j.task_state || j;
    out(`${bold("task")}      ${z.task_id || flags.id || "?"}`);
    out(`${bold("objective")} ${(z.objective || "").slice(0, 200)}`);
    out(`${bold("step")}      ${z.step ?? "?"}`);
    const open = (z.C || z.completion_criteria || []).filter((c) => !c.met);
    out(`${bold("open C")}    ${open.length}`);
    for (const c of open.slice(0, 8)) out(dim("  · ") + (c.text || c));
    const goals = z.G || z.goals || [];
    if (goals.length) {
      out(`${bold("goals")}`);
      for (const g of goals.slice(0, 6)) out(dim("  · ") + (g.text || g));
    }
    const plan = z.P || z.plan || [];
    if (plan.length) {
      out(`${bold("plan")}`);
      for (const p of plan.slice(0, 8)) out(dim(`  [${p.status||"?"}] `) + (p.text || p.id));
    }
    if (j.receipt) out(dim(`receipt blob keys: ${Object.keys(j.receipt).join(", ")}`));
    return 0;
  }
  fail(`unknown inspect target: ${sub}`, 2);
}

async function cmdMemory(sub, args, flags) {
  if (sub && !["list", "add", "forget"].includes(sub)) {
    fail(`unknown: lolm memory ${sub} (list | add | forget)`, 2);
  }
  if ((!sub || sub === "list") && args.length) fail("memory list accepts no extra arguments", 2);
  if (sub === "forget" && args.length) fail("memory forget accepts no extra arguments", 2);
  const o = clientOpts(flags);
  if (!o.apiKey) fail("authentication required for persistent memory (--api-key or LOLM_API_KEY)", 1);
  if (sub === "list" || !sub) {
    const facts = await getMemory({ baseUrl: flags.base, ...o });
    if (JSON_MODE) return emit(facts);
    if (!facts.length) { out(dim("nothing remembered yet")); return 0; }
    for (const f of facts) out(`${dim((f.id||"").slice(0, 8))}  ${f.text}`);
    return 0;
  }
  if (sub === "add") {
    const text = args.join(" ").trim();
    if (!text) fail("nothing to remember: lolm memory add <text>", 2);
    const res = await rememberFact({ text, baseUrl: flags.base, ...o });
    if (JSON_MODE) return emit(res);
    out(res.duplicate ? dim("already remembered") : green("remembered"));
    return 0;
  }
  if (sub === "forget") {
    if (!flags.id && !flags.all) fail("say which: --id <ID> or --all", 2);
    const res = await forgetMemory({ id: flags.id, all: flags.all, baseUrl: flags.base, ...o });
    if (JSON_MODE) return emit(res);
    out(green(flags.all ? `cleared ${res.cleared ?? 0}` : res.deleted ? "forgotten" : "not found"));
    return 0;
  }
  fail(`unknown: lolm memory ${sub} (list | add | forget)`, 2);
}

// ── entry ────────────────────────────────────────────────────────────────────

async function main() {
  // merge config defaults
  const cfg = await loadConfig().catch(() => ({}));
  const { flags, rest } = parseArgs(process.argv.slice(2));
  if (cfg.apiKey && !flags.apiKey) flags.apiKey = cfg.apiKey;
  if (cfg.license && !flags.license) flags.license = cfg.license;
  if (cfg.base && flags.base === DEFAULT_BASE && !process.env.LOLM_BASE_URL) {
    flags.base = normalizeBase(cfg.base);
  }

  if (flags.version) {
    if (JSON_MODE) emit({ schema: "lolm.cli.result.v2", ok: true, exit_code: 0, version: VERSION });
    else out(VERSION);
    return 0;
  }
  const [cmd, ...args] = rest;
  if (!cmd && !flags.help) { out(START); out(dim("Full help: lolm --help")); return 0; }
  if (flags.help) {
    if (JSON_MODE) emit({ schema: "lolm.cli.result.v2", ok: true, exit_code: 0, help: HELP });
    else out(HELP);
    return 0;
  }

  const text = args.join(" ").trim();
  switch (cmd) {
    case "status":
      if (args.length) fail("status accepts no positional arguments", 2);
      return (await cmdStatus(flags)) ?? 0;
    case "doctor":   return await cmdDoctor(flags);
    case "config":   return await cmdConfig(args[0], args.slice(1), flags);
    case "whoami":
      if (args.length) fail("whoami accepts no positional arguments", 2);
      return (await cmdWhoami(flags)) ?? 0;
    case "code":
      if (!text) fail('what should it build? e.g. lolm code "fizzbuzz in solution.py"', 2);
      return await cmdCode(text, flags);
    case "ask":
      if (!text) fail('what should it answer? e.g. lolm ask "what is a receipt?"', 2);
      return await cmdAsk(text, flags);
    case "build":
      if (!text) fail('what should it build? e.g. lolm build "a snake game"', 2);
      return await cmdBuild(text, flags);
    case "receipts":
      if (args.length) fail("receipts accepts no positional arguments", 2);
      return (await cmdReceipts(flags)) ?? 0;
    case "receipt":
      if (args[0] === "verify") return await cmdReceiptVerify(args[1], flags);
      fail("usage: lolm receipt verify <file|sha-prefix>", 2);
      break;
    case "inspect":  return await cmdInspect(args[0], args.slice(1), flags);
    case "memory":   return (await cmdMemory(args[0], args.slice(1), flags)) ?? 0;
    case "last":
      if (args.length) fail("last accepts no positional arguments", 2);
      return (await cmdLast(flags)) ?? 0;
    case "retry":
      return (await cmdRetry(args, flags)) ?? 0;
    case "resume":
      return (await cmdResume(args, flags)) ?? 0;
    case "help":     out(HELP); return 0;
    default:
      // Bare natural-language follow-ups: try session referent before hard-fail
      if (cmd && !cmd.startsWith("-")) {
        const p = await loadLatestSession();
        const joined = [cmd, ...args].join(" ").trim();
        const resolved = resolveFollowupLocal(joined, p);
        if (resolved.action === "retry" || resolved.action === "resume" || resolved.action === "retry_ask") {
          return (await cmdRetry([joined], flags)) ?? 0;
        }
        if (resolved.action === "clarify" && p) {
          out(yellow(resolved.prompt || "ambiguous follow-up — try `lolm last`"));
          return 2;
        }
      }
      fail(`unknown command "${cmd}" (try: lolm --help)`, 2);
  }
}

function renderFailure(error) {
  if (BROKEN_PIPE) return 0;
  const isAgent = error instanceof AgentRunError;
  const status = isAgent ? error.status : null;
  const hint = status === 429 ? " — rate limited, wait a moment"
    : status === 402 ? " — daily limit reached; see lolm.imagineqira.com/pricing.html"
    : status === 503 ? " — the sandbox is unavailable on this host"
    : "";
  const code = error?.code || (isAgent ? "AGENT_RUN_ERROR" : "UNEXPECTED_ERROR");
  const exitCode = SIGNAL_EXIT || error?.exitCode
    || (["TIMEOUT", "IDLE_TIMEOUT"].includes(code) ? 124 : code === "CANCELLED" ? 130 : 1);
  if (JSON_MODE) {
    emit({
      schema: "lolm.cli.result.v2",
      ok: false,
      exit_code: exitCode,
      error: { code, message: `${error?.message || String(error)}${hint}` },
    });
  } else if (!BROKEN_PIPE) {
    err(red("error: ") + `${error?.message || String(error)}${hint}`);
  }
  return exitCode;
}

main()
  .then((code) => {
    process.exitCode = SIGNAL_EXIT || (Number.isInteger(code) ? code : 0);
  })
  .catch((error) => {
    process.exitCode = renderFailure(error);
  });
