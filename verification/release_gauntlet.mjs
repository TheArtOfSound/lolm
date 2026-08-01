#!/usr/bin/env node
/**
 * Independent release gauntlet for the installed LOLM packages.
 *
 * Point LOLM_PACKAGE_ROOT and LOLM_JS_ROOT at unpacked/installed package roots
 * to test the artifact users receive rather than repository imports.
 */
import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, sign as cryptoSign } from "node:crypto";
import { spawnSync } from "node:child_process";
import { access, chmod, lstat, mkdtemp, mkdir, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const cliRoot = resolve(process.env.LOLM_PACKAGE_ROOT || join(here, "..", "clients", "cli"));
const jsRoot = resolve(process.env.LOLM_JS_ROOT || join(here, "..", "clients", "js"));
const imported = async (root, path) => import(pathToFileURL(join(root, path)).href);

const { safeDestination } = await imported(cliRoot, "lib/paths.mjs");
const { evaluateShipped } = await imported(cliRoot, "lib/shipped.mjs");
const { safeTerminal } = await imported(cliRoot, "lib/terminal.mjs");
const { verifyCodeReceipt, pyStyleDumps } = await imported(cliRoot, "lib/receipt.mjs");
const { installVerifiedArtifacts, manifestSha256 } = await imported(cliRoot, "lib/artifacts.mjs");
const { parseSSEStream } = await imported(jsRoot, "index.mjs");

let checks = 0;
const campaigns = {};
function check(condition, label) {
  checks++;
  assert.ok(condition, label);
}
function campaign(name, count) { campaigns[name] = (campaigns[name] || 0) + count; }

// Exit-code truth table: every incomplete or contradictory combination fails.
{
  const doneStates = [true, false, undefined, "malformed"];
  const receiptStates = ["present", "missing", "malformed"];
  const verdicts = ["shipped", "broken", "incomplete", "unknown", undefined];
  const tri = [true, false, undefined];
  const proofStates = ["valid", "invalid", "absent"];
  const streamStates = ["complete", "interrupted", "contradictory"];
  let cases = 0;
  let accepted = 0;
  let mutantFalsePositives = 0;
  for (const doneOk of doneStates)
  for (const receiptState of receiptStates)
  for (const verdict of verdicts)
  for (const syntaxOk of tri)
  for (const executionOk of tri)
  for (const contractOk of tri)
  for (const receiptProof of proofStates)
  for (const artifactProof of proofStates)
  for (const stream of streamStates) {
    const done = doneOk === "malformed" ? "bad" : {
      ok: doneOk,
      run_id: stream === "interrupted" ? undefined : "run_a",
    };
    let receipt = receiptState === "missing" ? null : receiptState === "malformed" ? "bad" : {
      schema: "lolm.code.receipt.v2",
      run_id: stream === "contradictory" ? "run_b" : "run_a",
      verdict,
      ok: verdict === "shipped" ? true : false,
      syntax_ok: syntaxOk,
      verification: {
        syntax_ok: syntaxOk,
        execution_ok: executionOk,
        contract_ok: contractOk,
        artifact_manifest_ok: artifactProof === "valid" ? true
          : artifactProof === "invalid" ? false : undefined,
      },
    };
    const expected = doneOk === true && receiptState === "present"
      && verdict === "shipped" && syntaxOk === true && executionOk === true
      && contractOk === true && receiptProof === "valid"
      && artifactProof === "valid" && stream === "complete";
    const result = evaluateShipped(done, receipt, {
      receiptVerified: receiptProof === "valid",
      saveRequested: true,
      artifactsVerified: artifactProof === "valid",
    });
    check(result.shipped === expected, `truth table case ${cases}`);
    if (result.shipped) accepted++;
    const mutant = Boolean(done?.ok === true || receipt?.verdict === "shipped");
    if (mutant && !expected) mutantFalsePositives++;
    cases++;
  }
  check(accepted === 1, "exactly one fully verified truth-table state ships");
  check(mutantFalsePositives > 0, "optimistic OR mutation is killed by the truth table");
  campaign("exit_truth_table", cases);
  campaigns.mutation_false_positives = mutantFalsePositives;
}

// Filesystem campaign: explicit cross-platform attacks plus deterministic fuzz.
{
  const root = resolve(tmpdir(), "lolm-gauntlet-root");
  const hostile = [
    "../outside.txt", "../../outside.txt", "/absolute/path", "C:\\outside.txt",
    "C:/outside.txt", "\\\\server\\share\\file", "..\\..\\outside.txt",
    "folder/../../../outside", "folder\\..\\..\\outside", "a\0b", "a//b",
    "a/./b", "C:outside", "CON", "aux.txt", "trail.", "trail ", ".", "..",
  ];
  for (const path of hostile) {
    let rejected = false;
    try { safeDestination(root, path); } catch { rejected = true; }
    check(rejected, `hostile path rejected: ${JSON.stringify(path)}`);
  }
  let state = 0x5eed1234;
  const atoms = ["safe", "src", "δ", "文件", "..", ".", "", "CON", "a:b", "trail.", "／", "∕"];
  for (let i = 0; i < 5000; i++) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    const depth = 1 + (state % 7);
    const parts = [];
    for (let j = 0; j < depth; j++) {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      parts.push(atoms[state % atoms.length] + ((state >>> 9) % 5));
    }
    const separator = (state & 1) ? "/" : "\\";
    const raw = parts.join(separator);
    try {
      const dest = safeDestination(root, raw);
      const rel = relative(root, dest);
      check(rel !== "" && rel !== ".." && !rel.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`), `contained fuzz path ${i}`);
    } catch {
      check(true, `safely rejected fuzz path ${i}`);
    }
  }
  campaign("filesystem_generated", hostile.length + 5000);
}

// EventSource framing and chunk-boundary campaign.
function byteStream(chunks) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}
async function parseChunks(chunks) {
  const events = [];
  for await (const event of parseSSEStream(byteStream(chunks))) events.push(event);
  return events;
}
{
  const encoder = new TextEncoder();
  const text = "event:data\r\ndata: first\r\ndata: second 😀\r\n\r\nevent: done\ndata:{\"ok\":true}\r\n";
  const bytes = encoder.encode(text);
  for (let split = 1; split < bytes.length; split++) {
    const events = await parseChunks([bytes.slice(0, split), bytes.slice(split)]);
    check(events.length === 2 && events[0].event === "data"
      && events[0].data === "first\nsecond 😀" && events[1].data.ok === true,
    `SSE split boundary ${split}`);
  }
  for (let size = 1; size <= 32; size++) {
    const chunks = [];
    for (let i = 0; i < bytes.length; i += size) chunks.push(bytes.slice(i, i + size));
    const events = await parseChunks(chunks);
    check(events.length === 2 && events[1].data.ok === true, `SSE chunk size ${size}`);
  }
  for (const ending of ["\n", "\r", "\r\n"]) {
    const raw = `: keepalive${ending}event: x${ending}data: 1${ending}${ending}`;
    const events = await parseChunks([encoder.encode(raw)]);
    check(events.length === 1 && events[0].event === "x" && events[0].data === 1, `SSE ending ${JSON.stringify(ending)}`);
  }
  campaign("sse_chunk_and_framing", bytes.length - 1 + 32 + 3);
}

// Terminal injection corpus.
{
  const payloads = [
    "\x1b[31mred\x1b[0m", "\x1b]0;title\x07", "\x1b]52;c;Y2xpcA==\x07",
    "\x1b[2Jclear", "\x1b[Hhome", "\x1bPdevice\x1b\\", "\x1b_hidden\x1b\\",
    "a\rb", "a\bb", "bell\x07", "\u202Eflip", "\u2066isolate", "\x9b31m",
    "\x00nul", "\x7fdel", "\x1b]8;;https://evil.invalid\x07link\x1b]8;;\x07",
  ];
  for (const payload of payloads) {
    const clean = safeTerminal(payload);
    check(!/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u202A-\u202E\u2066-\u2069]/u.test(clean), `terminal payload sanitized ${JSON.stringify(payload)}`);
  }
  campaign("terminal_payloads", payloads.length);
}

// Signed receipt tampering and timestamp policy.
function signedReceipt(core, privateKey, keyId = "gauntlet-key") {
  const signed = { ...core, signed_at: core.signed_at ?? Math.floor(Date.now() / 1000) };
  const blob = pyStyleDumps(signed);
  return {
    ...signed,
    receipt_sha: createHash("sha256").update(blob).digest("hex"),
    signature: { alg: "Ed25519", key_id: keyId,
      sig: cryptoSign(null, Buffer.from(blob), privateKey).toString("base64url") },
  };
}
{
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const publicKeys = { "gauntlet-key": publicKey.export({ type: "spki", format: "pem" }) };
  const core = {
    schema: "lolm.code.receipt.v2", run_id: "run_gauntlet", task: "exact task",
    model_used: "test-model", verdict: "shipped", ok: true, syntax_ok: true,
    files: ["a.txt"],
    verification: { syntax_ok: true, execution_ok: true, contract_ok: true,
      artifact_manifest_ok: true, artifact_manifest_sha256: "a".repeat(64) },
  };
  const good = signedReceipt(core, privateKey);
  check(verifyCodeReceipt(good, { publicKeys }).integrity.verified === true, "valid signed receipt verifies");
  const mutations = [
    (r) => { r.task = "changed"; }, (r) => { r.model_used = "other"; },
    (r) => { r.verdict = "broken"; }, (r) => { r.ok = false; },
    (r) => { r.syntax_ok = false; }, (r) => { r.run_id = "other"; },
    (r) => { r.files = ["b.txt"]; }, (r) => { r.verification.syntax_ok = false; },
    (r) => { r.verification.execution_ok = false; }, (r) => { r.verification.contract_ok = false; },
    (r) => { r.verification.artifact_manifest_ok = false; },
    (r) => { r.verification.artifact_manifest_sha256 = "b".repeat(64); },
    (r) => { r.signed_at += 1; }, (r) => { r.receipt_sha = "0".repeat(64); },
    (r) => { delete r.signature; }, (r) => { r.signature.sig = "AA"; },
    (r) => { r.signature.key_id = "wrong"; }, (r) => { delete r.run_id; },
  ];
  for (const [i, mutate] of mutations.entries()) {
    const receipt = structuredClone(good);
    mutate(receipt);
    check(verifyCodeReceipt(receipt, { publicKeys }).integrity.verified === false, `receipt mutation ${i}`);
  }
  const future = signedReceipt({ ...core, signed_at: Math.floor(Date.now() / 1000) + 86_400 }, privateKey);
  check(verifyCodeReceipt(future, { publicKeys }).integrity.verified === false, "properly signed future receipt rejected");
  campaign("receipt_tampering", mutations.length + 2);
}

// Exact bytes, executable metadata, safe staging, and symlinked-parent refusal.
{
  const root = await mkdtemp(join(tmpdir(), "lolm-gauntlet-artifacts-"));
  const variants = [
    Buffer.alloc(0), Buffer.from([0]), Buffer.from("no newline"), Buffer.from("one\n"),
    Buffer.from("many\n\n\n"), Buffer.from("crlf\r\n"), Buffer.from("mixed\r\nlf\n"),
    Buffer.from("\ttabs\t"), Buffer.from("unicode 😀 文件"), Buffer.from([0, 1, 2, 255]),
    Buffer.alloc(64 * 1024, 0x61), Buffer.from("#!/bin/sh\necho ok\n"),
  ];
  const files = variants.map((content, i) => ({
    path: `group-${i % 3}/file-${i}.bin`, type: "file", size: content.length,
    sha256: createHash("sha256").update(content).digest("hex"), encoding: "base64",
    content_base64: content.toString("base64"), executable: i === variants.length - 1,
  }));
  const manifest = { schema: "lolm.artifact.manifest.v1", run_id: "run_artifacts",
    artifact_id: "artifact_exact", complete: true, files };
  manifest.manifest_sha256 = manifestSha256(manifest);
  const dest = join(root, "exact-output");
  const result = await installVerifiedArtifacts(dest, manifest);
  check(result.verified === true && result.files.length === files.length, "artifact tree committed and verified");
  for (let i = 0; i < files.length; i++) {
    const actual = await readFile(join(dest, files[i].path));
    check(actual.equals(variants[i]), `artifact exact bytes ${i}`);
  }
  const executable = await lstat(join(dest, files.at(-1).path));
  check(process.platform === "win32" || (executable.mode & 0o111) !== 0, "executable metadata preserved");

  const outside = join(root, "outside");
  await mkdir(outside);
  const link = join(root, "linked-parent");
  await symlink(outside, link, process.platform === "win32" ? "junction" : "dir");
  let rejected = false;
  try { await installVerifiedArtifacts(join(link, "escaped"), manifest); } catch { rejected = true; }
  check(rejected, "symlinked destination parent rejected");
  let escaped = true;
  try { await access(join(outside, "escaped")); } catch { escaped = false; }
  check(escaped === false, "symlinked parent produced no outside tree");
  campaign("artifact_fidelity", variants.length + 4);
}

// Parser and numeric boundary matrix through the actual package binary.
{
  const bin = join(cliRoot, "bin", "lolm.mjs");
  const configRoot = await mkdtemp(join(tmpdir(), "lolm-gauntlet-config-"));
  const env = { ...process.env, LOLM_CONFIG: join(configRoot, "missing.json"), NO_COLOR: "1" };
  const invoke = (args, options = {}) => spawnSync(process.execPath, [bin, ...args], {
    cwd: options.cwd || configRoot, env, encoding: "utf8", timeout: 5000,
    maxBuffer: 8 * 1024 * 1024,
  });
  for (const args of [["--version"], ["--help"], ["--json", "--help"], []]) {
    const r = invoke(args);
    check(r.status === 0, `valid parser case ${args.join(" ")}`);
    if (args.includes("--json")) check(JSON.parse(r.stdout).ok === true, "JSON help document");
  }
  const missing = [
    ["status", "--base"], ["status", "--timeout"], ["code", "x", "--idle-timeout"],
    ["code", "x", "--save"], ["code", "x", "--max-steps"], ["build", "x", "--out"],
    ["receipts", "--limit"], ["memory", "forget", "--id"], ["code", "x", "--receipt"],
  ];
  for (const args of missing) check(invoke(args).status === 2, `missing value ${args.join(" ")}`);
  const numeric = ["", " ", "-1", "0", "1.5", "NaN", "Infinity", "1e3", "0x10",
    "+1", "999999999999999999999999"];
  for (const value of numeric) {
    for (const [cmd, flag] of [["receipts", "--limit"], ["code", "--max-steps"], ["status", "--timeout"]]) {
      const args = cmd === "code" ? [cmd, "x", flag, value] : [cmd, flag, value];
      check(invoke(args).status === 2, `invalid numeric ${flag}=${JSON.stringify(value)}`);
    }
  }
  const commandFlags = {
    status: ["--save", "x", "--out", "x", "--limit", "1", "--quiet"],
    receipts: ["--save", "x", "--out", "x", "--max-steps", "1", "--quiet"],
    memory: ["--save", "x", "--out", "x", "--max-steps", "1", "--quiet"],
  };
  for (const [cmd, tokens] of Object.entries(commandFlags)) {
    for (let i = 0; i < tokens.length; i += tokens[i].startsWith("--") && !["--quiet"].includes(tokens[i]) ? 2 : 1) {
      const args = [cmd, ...tokens.slice(i, i + (tokens[i] === "--quiet" ? 1 : 2))];
      check(invoke(args).status === 2, `irrelevant flag ${args.join(" ")}`);
    }
  }
  for (const command of ["status", "receipts", "memory"]) {
    check(invoke([command, "extra"]).status === 2, `extra positional rejected for ${command}`);
  }
  for (const value of ["file:///tmp/x", "http://example.com", "https://u:p@example.com", "not a url",
    "javascript:alert(1)", "https://example.com/path", "https://example.com/?x=1"] ) {
    check(invoke(["status", "--base", value]).status === 2, `unsafe base rejected ${value}`);
  }
  const jsonErrors = [
    ["--json", "frobnicate"], ["status", "--json", "--nope"],
    ["code", "--json"], ["receipts", "--json", "extra"],
  ];
  for (const args of jsonErrors) {
    const r = invoke(args);
    check([1, 2].includes(r.status), `JSON error nonzero ${args.join(" ")}`);
    const doc = JSON.parse(r.stdout);
    check(doc.ok === false && Number.isInteger(doc.exit_code) && r.stdout.trim().split("\n").length === 1,
      `one JSON error ${args.join(" ")}`);
  }
  campaign("parser_and_process", 4 + 1 + missing.length + numeric.length * 3
    + Object.values(commandFlags).reduce((n, values) => n + Math.ceil(values.length / 2), 0)
    + 3 + 7 + jsonErrors.length * 2);
}

const summary = {
  schema: "lolm.release.gauntlet.v1",
  ok: true,
  cli_root: cliRoot,
  js_root: jsRoot,
  assertions: checks,
  campaigns,
  node: process.version,
  platform: `${process.platform}-${process.arch}`,
};
process.stdout.write(JSON.stringify(summary, null, 2) + "\n");
