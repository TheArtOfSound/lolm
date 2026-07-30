#!/usr/bin/env node
// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * lolm — command-line client for the LOLM agent.
 *
 * Runs a coding task in a network-isolated jail, streams the real write → run →
 * read-the-error → fix loop, and ends with a sealed receipt. The receipt is the
 * point: `lolm code` exits non-zero unless the delivered code actually compiled and
 * ran, so it is safe to put in a script.
 */

import { writeFile, mkdir } from "node:fs/promises";
import { dirname, join, resolve, isAbsolute } from "node:path";
import process from "node:process";
import {
  runAgent, runCode, buildVisual, listCodeReceipts, getStatus,
  getMemory, rememberFact, forgetMemory, friendly, AgentRunError,
} from "lolm-nfet-client";
import { replayFileChanges } from "../lib/diff.mjs";

const VERSION = "0.1.0";
const DEFAULT_BASE = "https://lolm.imagineqira.com";

// ── output ───────────────────────────────────────────────────────────────────

const useColor =
  process.stdout.isTTY && !process.env.NO_COLOR && process.env.TERM !== "dumb";
const c = (code) => (s) => (useColor ? `\x1b[${code}m${s}\x1b[0m` : String(s));
const dim = c("2"), bold = c("1"), red = c("31"), green = c("32");
const yellow = c("33"), blue = c("34"), magenta = c("35"), cyan = c("36");

let JSON_MODE = false;
const out = (s = "") => process.stdout.write(s + "\n");
const err = (s = "") => process.stderr.write(s + "\n");
/** Progress goes to stderr so `lolm build x > app.html` stays clean. */
const log = (s = "") => { if (!JSON_MODE) err(s); };
const emit = (obj) => out(JSON.stringify(obj));

function fail(msg, code = 1) {
  if (JSON_MODE) emit({ ok: false, error: msg });
  else err(red("error: ") + msg);
  process.exit(code);
}

// ── args ─────────────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const flags = { base: process.env.LOLM_BASE_URL || DEFAULT_BASE };
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--json") JSON_MODE = flags.json = true;
    else if (a === "--quiet" || a === "-q") flags.quiet = true;
    else if (a === "--help" || a === "-h") flags.help = true;
    else if (a === "--version" || a === "-V") flags.version = true;
    else if (a === "--base") flags.base = argv[++i];
    else if (a === "--save") flags.save = argv[++i];
    else if (a === "--out" || a === "-o") flags.out = argv[++i];
    else if (a === "--limit") flags.limit = parseInt(argv[++i], 10);
    else if (a === "--max-steps") flags.maxSteps = parseInt(argv[++i], 10);
    else if (a === "--all") flags.all = true;
    else if (a === "--id") flags.id = argv[++i];
    else if (a.startsWith("--")) fail(`unknown flag ${a} (try: lolm --help)`, 2);
    else rest.push(a);
  }
  if (flags.base) flags.base = String(flags.base).replace(/\/+$/, "");
  return { flags, rest };
}

const HELP = `${bold("lolm")} — command-line client for the LOLM agent  ${dim("v" + VERSION)}

${bold("USAGE")}
  lolm <command> [args] [flags]

${bold("COMMANDS")}
  code <task...>        Run the agentic coding loop in a jailed sandbox.
                        Streams write → run → fix. Exits non-zero unless the
                        delivered code compiled and ran.
  ask <question...>     Ask the agent, streaming its answer and the control
                        decisions it made while writing it.
  build <app...>        Build a self-contained visual app (HTML) and save it.
  receipts              Recent sealed code receipts from the public ledger.
  status                Model + API status and the current run limits.
  memory list           Durable facts the agent remembers about you.
  memory add <text>     Remember a fact.
  memory forget         Forget one (--id ID) or all of them (--all).

${bold("FLAGS")}
  --base <url>          API base (default ${DEFAULT_BASE},
                        or $LOLM_BASE_URL). Point this at your own instance.
  --save <dir>          code: write the sandbox files it produced into <dir>.
  --out, -o <file>      build: output path (default lolm-app.html).
  --max-steps <n>       code: cap the loop's steps.
  --limit <n>           receipts: how many rows.
  --json                Machine-readable output on stdout; progress on stderr.
  --quiet, -q           Only the outcome, no live loop.
  --help, -h            This help.  --version, -V   Print the version.

${bold("EXAMPLES")}
  lolm code "write fizzbuzz to 20 in solution.py and run it" --save ./out
  lolm ask "what is a sealed receipt?"
  lolm build "a snake game" -o snake.html
  lolm receipts --limit 5 --json | jq '.receipts[].verdict'

Every ${bold("code")} run ends with a receipt: a hashed record of the files written, the
commands run, their real exit codes, and whether the delivered code compiled.
`;

// ── commands ─────────────────────────────────────────────────────────────────

async function cmdStatus({ base }) {
  const s = await getStatus({ baseUrl: base });
  if (JSON_MODE) return emit(s);
  out(`${bold("model")}     ${s.model_ready ? green("ready") : yellow("not ready")}` +
      `${s.busy ? dim("  (busy)") : ""}`);
  out(`${bold("runs")}      ${s.runs_completed}/${s.runs_started} completed` +
      (s.last_run_seconds != null ? dim(`  last ${s.last_run_seconds}s`) : ""));
  out(`${bold("replays")}   ${s.replays}`);
  const L = s.limits || {};
  if (L.reasoner) out(`${bold("reasoner")}  ${L.reasoner}`);
  const shown = ["max_segments", "final_tokens", "rate_per_hour"].filter((k) => k in L);
  if (shown.length) out(dim("limits    " + shown.map((k) => `${k}=${L[k]}`).join("  ")));
}

async function cmdCode(task, { base, save, maxSteps, quiet }) {
  const changes = [];
  let lastStep = -1;
  const done = await runCode({
    task, baseUrl: base, maxSteps,
    onEvent(ev) {
      const d = ev.data || {};
      if (JSON_MODE) { if (!quiet) err(dim(ev.event)); return; }
      switch (ev.event) {
        case "code_start":
          log(dim(`sandbox ${d.sandbox}`));
          break;
        case "code_thinking":
          if (!quiet && d.step !== lastStep) {
            lastStep = d.step;
            log(dim(`\n· step ${d.step + 1}/${d.of}`));
          }
          break;
        case "file_changed":
          changes.push({ path: d.path, diff: d.diff });
          if (!quiet) log(`  ${cyan("write")}  ${d.path} ${dim(`(${d.bytes}b)`)}` +
                          (d.edit ? dim(" [edit]") : ""));
          break;
        case "command_started":
          if (!quiet) log(`  ${blue("run")}    ${d.command}` +
                          (d.verify ? dim(" [verify]") : ""));
          break;
        case "command_finished": {
          if (quiet) break;
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
          if (!quiet && d.text) log(`  ${magenta("note")}   ${d.text}`);
          break;
        case "error":
          err(red("  stream error: ") + (d.error || "unknown"));
          break;
      }
    },
  });

  const r = done.receipt || {};
  const shipped = r.verdict === "shipped" || (done.ok === true && r.syntax_ok !== false);

  if (save && changes.length) {
    const dir = isAbsolute(save) ? save : resolve(process.cwd(), save);
    const { files, failed } = replayFileChanges(changes);
    for (const [p, text] of files) {
      const dest = join(dir, p);
      await mkdir(dirname(dest), { recursive: true });
      await writeFile(dest, text, "utf8");
    }
    done.saved = { dir, files: [...files.keys()], unavailable: Object.fromEntries(failed) };
    if (!JSON_MODE) {
      if (files.size) out(`\n${green("saved")} ${files.size} file(s) → ${dir}`);
      for (const [p, why] of failed) {
        err(yellow(`  skipped ${p}: `) + why +
            dim(" — the API truncates large diffs, so its full body never arrived"));
      }
    }
  }

  if (JSON_MODE) { emit({ ok: shipped, done }); return shipped ? 0 : 1; }

  out("");
  out(`${bold("verdict")}   ${shipped ? green(r.verdict || "shipped") : red(r.verdict || "incomplete")}`);
  if (done.summary) out(`${bold("summary")}   ${done.summary}`);
  if (r.files?.length) out(`${bold("files")}     ${r.files.join(", ")}`);
  if (r.syntax_ok === false && r.syntax_error) {
    out(`${bold("syntax")}    ${red("does not compile")} ${dim(r.syntax_error.split("\n").pop())}`);
  }
  const runs = [r.green_runs, r.failed_runs].some((v) => v != null)
    ? `${r.green_runs ?? 0} green / ${r.failed_runs ?? 0} failed` : null;
  if (runs) out(`${bold("runs")}      ${runs}`);
  if (r.receipt_sha) out(`${bold("receipt")}   ${dim(r.receipt_sha)}`);
  return shipped ? 0 : 1;
}

async function cmdAsk(question, { base, quiet }) {
  let printed = false;
  const res = await runAgent({
    command: question, baseUrl: base,
    onToken(t) {
      if (JSON_MODE) return;
      if (t.channel === "final" || t.channel === "draft") {
        process.stdout.write(t.token); printed = true;
      }
    },
    onEvent(ev) {
      if (JSON_MODE || quiet) return;
      const line = friendly(ev);
      if (line) err(dim("  · ") + line);
    },
  });
  if (JSON_MODE) return emit(res);
  if (printed) out("");
  const p = res.proof || {};
  if (!quiet && p.plain) out("\n" + dim(p.plain));
  const counts = Object.entries(p.control_counts || {})
    .filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join("  ");
  if (counts) out(dim(`decisions  ${counts}`));
  return 0;
}

async function cmdBuild(task, { base, out: outPath }) {
  const dest = outPath || "lolm-app.html";
  log(dim("building… (a real headless-browser check runs server-side)"));
  const res = await buildVisual({ task, baseUrl: base });
  const p = isAbsolute(dest) ? dest : resolve(process.cwd(), dest);
  await mkdir(dirname(p), { recursive: true });
  await writeFile(p, res.html, "utf8");
  if (JSON_MODE) return emit({ ok: true, path: p, bytes: res.bytes ?? res.html.length });
  out(`${green("built")} ${res.bytes ?? res.html.length} bytes → ${p}`);
  return 0;
}

async function cmdReceipts({ base, limit }) {
  const { receipts = [], stats = {} } = await listCodeReceipts({
    baseUrl: base, limit: limit || 10,
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

async function cmdMemory(sub, args, { base, id, all }) {
  if (sub === "list" || !sub) {
    const facts = await getMemory({ baseUrl: base });
    if (JSON_MODE) return emit(facts);
    if (!facts.length) { out(dim("nothing remembered yet")); return 0; }
    for (const f of facts) out(`${dim(f.id.slice(0, 8))}  ${f.text}`);
    return 0;
  }
  if (sub === "add") {
    const text = args.join(" ").trim();
    if (!text) fail("nothing to remember: lolm memory add <text>", 2);
    const res = await rememberFact({ text, baseUrl: base });
    if (JSON_MODE) return emit(res);
    out(res.duplicate ? dim("already remembered") : green("remembered"));
    return 0;
  }
  if (sub === "forget") {
    if (!id && !all) fail("say which: --id <ID> or --all", 2);
    const res = await forgetMemory({ id, all, baseUrl: base });
    if (JSON_MODE) return emit(res);
    out(green(all ? `cleared ${res.cleared ?? 0}` : res.deleted ? "forgotten" : "not found"));
    return 0;
  }
  fail(`unknown: lolm memory ${sub} (list | add | forget)`, 2);
}

// ── entry ────────────────────────────────────────────────────────────────────

async function main() {
  const { flags, rest } = parseArgs(process.argv.slice(2));
  if (flags.version) { out(VERSION); return 0; }
  const [cmd, ...args] = rest;
  if (flags.help || !cmd) { out(HELP); return cmd ? 0 : (rest.length ? 0 : 0); }

  const text = args.join(" ").trim();
  switch (cmd) {
    case "status":   return (await cmdStatus(flags)) ?? 0;
    case "code":
      if (!text) fail('what should it build? e.g. lolm code "fizzbuzz in solution.py"', 2);
      return await cmdCode(text, flags);
    case "ask":
      if (!text) fail('what should it answer? e.g. lolm ask "what is a receipt?"', 2);
      return await cmdAsk(text, flags);
    case "build":
      if (!text) fail('what should it build? e.g. lolm build "a snake game"', 2);
      return await cmdBuild(text, flags);
    case "receipts": return (await cmdReceipts(flags)) ?? 0;
    case "memory":   return (await cmdMemory(args[0], args.slice(1), flags)) ?? 0;
    case "help":     out(HELP); return 0;
    default:
      fail(`unknown command "${cmd}" (try: lolm --help)`, 2);
  }
}

main()
  .then((code) => process.exit(code || 0))
  .catch((e) => {
    if (e instanceof AgentRunError) {
      const hint = e.status === 429 ? " — rate limited, wait a moment"
        : e.status === 402 ? " — daily limit reached; see lolm.imagineqira.com/pricing.html"
        : e.status === 503 ? " — the sandbox is unavailable on this host"
        : "";
      fail(`${e.message}${hint}`, 1);
    }
    fail(e?.message || String(e), 1);
  });
