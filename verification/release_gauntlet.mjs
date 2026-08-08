#!/usr/bin/env node
/** Independent release checks for the local/BYOK npm artifact. */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { access, mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const cliRoot = resolve(process.env.LOLM_PACKAGE_ROOT || join(here, "..", "clients", "cli"));
const imported = (path) => import(pathToFileURL(join(cliRoot, path)).href);
const { PROVIDERS } = await imported("lib/config.mjs");
const { createPdf } = await imported("lib/pdf.mjs");
const { createToolRunner } = await imported("lib/tools.mjs");
const pkg = JSON.parse(await readFile(join(cliRoot, "package.json"), "utf8"));

let checks = 0;
function check(value, message) { checks++; assert.ok(value, message); }

check(pkg.name === "lolm-cli" && pkg.license === "AGPL-3.0-or-later", "package identity and license");
check(pkg.bin?.lolm === "bin/lolm.mjs", "package exposes one local CLI binary");
for (const required of ["lib/agent.mjs", "lib/config.mjs", "lib/nfet_bridge.py", "lib/providers.mjs", "lib/tools.mjs", "lib/tui.mjs"]) {
  check(pkg.files.includes(required), `package includes ${required}`);
}
for (const legacy of ["lib/delivery.mjs", "lib/shipped.mjs", "lib/receipt.mjs", "lib/artifacts.mjs"]) {
  check(!pkg.files.includes(legacy), `package excludes hosted-era ${legacy}`);
}
check(Object.keys(PROVIDERS).length >= 12, "provider catalog supports broad BYOK selection");
check(PROVIDERS.ollama.noKey === true && PROVIDERS.custom.protocol === "openai", "local and custom providers are first-class");

const work = await mkdtemp(join(tmpdir(), "lolm-release-"));
const pdfPath = join(work, "proof.pdf");
const pdf = await createPdf("Local PDF creation works.", pdfPath, { title: "LOLM release proof" });
check(pdf.bytes > 300, "PDF artifact has substantive bytes");
check((await readFile(pdfPath)).subarray(0, 5).toString() === "%PDF-", "PDF artifact has valid header");

const runner = createToolRunner({ cwd: work, yes: true });
const write = await runner.execute({ name: "write_file", arguments: { path: "nested/proof.txt", content: "verified\n" } });
check(write.ok && (await readFile(join(work, "nested", "proof.txt"), "utf8")) === "verified\n", "approved local write is exact");
const blocked = await runner.execute({ name: "run_command", arguments: { command: "rm -rf /" } });
check(blocked.ok === false && /blocked/.test(blocked.error), "destructive command guard rejects broad deletion");
const dryPath = join(work, "dry.txt");
const dry = await createToolRunner({ cwd: work, yes: true, dryRun: true }).execute({ name: "write_file", arguments: { path: dryPath, content: "no" } });
check(dry.ok && dry.dry_run && !await access(dryPath).then(() => true).catch(() => false), "dry run never writes");

const bin = join(cliRoot, "bin", "lolm.mjs");
const env = { ...process.env, LOLM_CONFIG: join(work, "missing.json"), NO_COLOR: "1" };
const invoke = (args) => spawnSync(process.execPath, [bin, ...args], { cwd: work, env, encoding: "utf8", timeout: 15_000 });
for (const args of [["--version"], ["--help"], ["--json", "--help"], ["providers", "--json"], ["nfet", "status", "--json"]]) {
  const result = invoke(args);
  check(result.status === 0, `CLI succeeds: ${args.join(" ")}`);
  if (args.includes("--json")) check(JSON.parse(result.stdout).ok !== undefined, `CLI emits one JSON document: ${args.join(" ")}`);
}
for (const value of ["", " ", "-1", "0", "1.5", "NaN", "Infinity", "1e3", "+1", "999999999999999999999999"]) {
  const result = invoke(["ask", "hello", "--max-steps", value, "--json"]);
  check(result.status === 2, `invalid --max-steps rejected: ${JSON.stringify(value)}`);
  const doc = JSON.parse(result.stdout);
  check(doc.ok === false && doc.exit_code === 2, "numeric parser error is stable JSON");
}
for (const args of [["--nope", "--json"], ["pdf", "--json"], ["request", "get", "--json"]]) {
  const result = invoke(args);
  check(result.status === 2, `invalid invocation exits 2: ${args.join(" ")}`);
  check(JSON.parse(result.stdout).ok === false, "invalid invocation is machine-readable");
}

process.stdout.write(`${JSON.stringify({ schema: "lolm.release.gauntlet.v2", ok: true, assertions: checks, cli_root: cliRoot, node: process.version, platform: `${process.platform}-${process.arch}` }, null, 2)}\n`);
