import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";

import { safeDestination, isSafeUnder } from "../clients/cli/lib/paths.mjs";
import { safeTerminal } from "../clients/cli/lib/terminal.mjs";
import { evaluateShipped, evaluateAskOk } from "../clients/cli/lib/shipped.mjs";
import {
  extractSignedCore,
  pyStyleDumps,
  verifyCodeReceipt,
} from "../clients/cli/lib/receipt.mjs";
import {
  manifestSha256,
  validateManifest,
  installVerifiedArtifacts,
} from "../clients/cli/lib/artifacts.mjs";
import { parseSSEStream } from "../clients/js/index.mjs";

const BIN = resolve("clients/cli/bin/lolm.mjs");
let checks = 0;
const check = (condition, message) => { checks += 1; assert.ok(condition, message); };
const equal = (actual, expected, message) => { checks += 1; assert.equal(actual, expected, message); };
const rejects = async (fn, pattern, message) => {
  checks += 1;
  await assert.rejects(fn, pattern, message);
};
const throws = (fn, pattern, message) => {
  checks += 1;
  assert.throws(fn, pattern, message);
};

function sha(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function validDone() {
  return { ok: true, run_id: "run-independent-1" };
}

function validReceiptCore() {
  return {
    schema: "lolm.code.receipt.v2",
    run_id: "run-independent-1",
    verdict: "shipped",
    ok: true,
    syntax_ok: true,
    signed_at: Math.floor(Date.now() / 1000),
    verification: {
      syntax_ok: true,
      execution_ok: true,
      contract_ok: true,
      artifact_manifest_ok: true,
      artifact_manifest_sha256: "a".repeat(64),
    },
  };
}

const { publicKey, privateKey } = generateKeyPairSync("ed25519");
function sealReceipt(overrides = {}) {
  const receipt = structuredClone({ ...validReceiptCore(), ...overrides });
  const blob = pyStyleDumps(extractSignedCore(receipt));
  receipt.receipt_sha = sha(Buffer.from(blob));
  receipt.signature = {
    alg: "Ed25519",
    key_id: "independent-test-key",
    sig: sign(null, Buffer.from(blob), privateKey).toString("base64url"),
  };
  return receipt;
}

async function pathCampaign() {
  const root = resolve(tmpdir(), "lolm-path-root");
  const bad = [
    "../outside", "../../outside", "/etc/passwd", "C:/outside", "C:\\outside",
    "\\\\server\\share\\file", "//server/share", "a/../b", "a/./b", "a//b",
    "", ".", "..", "a/", "a\\..\\b", "CON", "nul.txt", "LPT9.log",
    "name.", "name ", "a:b", "\0bad", "dir/\0bad", "./x", "x/../../y",
  ];
  for (const p of bad) {
    check(!isSafeUnder(root, p), `unsafe path accepted: ${JSON.stringify(p)}`);
    throws(() => safeDestination(root, p), /rejected|unsafe|escaped|empty/i, `unsafe path did not throw: ${p}`);
  }
  for (let i = 0; i < 12000; i++) {
    const p = `segment-${i}/nested-${i % 97}/file-${i}.txt`;
    const dest = safeDestination(root, p);
    check(dest.startsWith(root), `safe path escaped root: ${p}`);
  }
  for (let i = 0; i < 12000; i++) {
    const p = i % 4 === 0 ? `a/${"../".repeat((i % 5) + 1)}escape-${i}`
      : i % 4 === 1 ? `C:/escape-${i}`
      : i % 4 === 2 ? `safe//escape-${i}`
      : `safe/./escape-${i}`;
    check(!isSafeUnder(root, p), `generated unsafe path accepted: ${p}`);
  }
}

function verdictTruthTable() {
  const done = validDone();
  const receipt = sealReceipt();
  let r = evaluateShipped(done, receipt, { receiptVerified: true });
  check(r.shipped, `valid evidence rejected: ${r.reasons.join(",")}`);

  const mutations = [
    ["missing receipt", null],
    ["empty receipt", {}],
    ["broken verdict", { ...receipt, verdict: "broken" }],
    ["missing verdict", { ...receipt, verdict: undefined }],
    ["receipt ok false", { ...receipt, ok: false }],
    ["syntax false", { ...receipt, syntax_ok: false }],
    ["verify syntax false", { ...receipt, verification: { ...receipt.verification, syntax_ok: false } }],
    ["execution false", { ...receipt, verification: { ...receipt.verification, execution_ok: false } }],
    ["contract false", { ...receipt, verification: { ...receipt.verification, contract_ok: false } }],
    ["manifest false", { ...receipt, verification: { ...receipt.verification, artifact_manifest_ok: false } }],
    ["run mismatch", { ...receipt, run_id: "different" }],
  ];
  for (const [name, mutated] of mutations) {
    r = evaluateShipped(done, mutated, { receiptVerified: true });
    check(!r.shipped, `${name} shipped`);
  }
  check(!evaluateShipped({ ...done, ok: false }, receipt, { receiptVerified: true }).shipped, "done.ok false shipped");
  check(!evaluateShipped(done, receipt, { receiptVerified: false }).shipped, "unverified receipt shipped");
  check(!evaluateShipped(done, receipt, { receiptVerified: true, saveRequested: true, artifactsVerified: false }).shipped,
    "unverified saved artifacts shipped");
  check(evaluateShipped(done, receipt, { receiptVerified: true, saveRequested: true, artifactsVerified: true }).shipped,
    "fully verified save did not ship");

  for (let mask = 0; mask < 512; mask++) {
    const x = structuredClone(receipt);
    const flags = [
      () => { x.verdict = "broken"; },
      () => { x.ok = false; },
      () => { x.syntax_ok = false; },
      () => { x.verification.syntax_ok = false; },
      () => { x.verification.execution_ok = false; },
      () => { x.verification.contract_ok = false; },
      () => { x.verification.artifact_manifest_ok = false; },
      () => { x.run_id = "other"; },
      () => { x.schema = "unknown"; },
    ];
    for (let bit = 0; bit < flags.length; bit++) if (mask & (1 << bit)) flags[bit]();
    const out = evaluateShipped(done, x, { receiptVerified: true });
    equal(out.shipped, mask === 0, `truth-table mask ${mask}`);
  }

  check(!evaluateAskOk(null).ok, "missing ask result accepted");
  check(!evaluateAskOk({ proof: { verdict: "failed" } }).ok, "failed ask proof accepted");
  check(evaluateAskOk({ proof: { verdict: "nfet_control_visible" }, answer: "ok" }).ok, "valid ask rejected");
}

function receiptCampaign() {
  const receipt = sealReceipt();
  let out = verifyCodeReceipt(receipt, { publicKeys: { "independent-test-key": publicKey } });
  check(out.integrity.verified, `valid signed receipt rejected: ${out.notes.join(";")}`);
  check(out.shipped_allowed, "valid signed receipt not allowed to ship");

  const contradictionFields = [
    ["verdict", "broken"], ["ok", false], ["syntax_ok", false], ["run_id", ""],
    ["schema", "other"], ["signed_at", Math.floor(Date.now() / 1000) + 3600],
  ];
  for (const [field, value] of contradictionFields) {
    const bad = sealReceipt({ [field]: value });
    out = verifyCodeReceipt(bad, { publicKeys: { "independent-test-key": publicKey } });
    check(!out.integrity.verified, `contradictory ${field} verified`);
  }
  for (const field of ["syntax_ok", "execution_ok", "contract_ok", "artifact_manifest_ok"]) {
    const core = validReceiptCore();
    core.verification[field] = false;
    const bad = sealReceipt(core);
    out = verifyCodeReceipt(bad, { publicKeys: { "independent-test-key": publicKey } });
    check(!out.integrity.verified, `verification.${field}=false verified`);
  }
  const tampered = sealReceipt();
  tampered.verdict = "broken";
  out = verifyCodeReceipt(tampered, { publicKeys: { "independent-test-key": publicKey } });
  check(!out.integrity.verified && !out.receipt_hash_match, "tampered receipt verified");
  out = verifyCodeReceipt(receipt, { publicKeys: {} });
  check(!out.integrity.verified && out.signature_valid !== true, "unknown signing key verified");
}

function terminalCampaign() {
  const payloads = [
    "safe\u001b[31mRED\u001b[0m", "x\u001b]0;TITLE\u0007y",
    "x\u001b]52;c;Y2xpcGJvYXJk\u0007y", "x\u001bPsecret\u001b\\y",
    "a\rb", "a\u202eb", "a\u2066b", "a\u0008b", "a\u009bb",
  ];
  for (const p of payloads) {
    const clean = safeTerminal(p);
    check(!/[\u001b\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u000d\u202a-\u202e\u2066-\u2069]/u.test(clean),
      `terminal control survived: ${JSON.stringify(clean)}`);
  }
  for (let i = 0; i < 5000; i++) {
    const p = `before\u001b]52;c;${Buffer.from(String(i)).toString("base64")}\u0007after\u202e${i}`;
    const clean = safeTerminal(p);
    check(!clean.includes("\u001b") && !clean.includes("\u202e"), `generated terminal payload survived ${i}`);
  }
}

function makeManifest(files, runId = "run-independent-1") {
  const manifest = {
    schema: "lolm.artifact.manifest.v1",
    run_id: runId,
    artifact_id: "artifact-independent-1",
    complete: true,
    files: files.map(({ path, bytes, executable = false, encoding = "base64" }) => ({
      path,
      type: "file",
      size: bytes.length,
      sha256: sha(bytes),
      executable,
      encoding,
      ...(encoding === "base64" ? { content_base64: bytes.toString("base64") } : { content: bytes.toString("utf8") }),
    })),
  };
  manifest.manifest_sha256 = manifestSha256(manifest);
  return manifest;
}

async function artifactCampaign() {
  const base = await mkdtemp(join(tmpdir(), "lolm-independent-"));
  try {
    const files = [
      { path: "no-newline.txt", bytes: Buffer.from("no newline") },
      { path: "one-newline.txt", bytes: Buffer.from("one newline\n") },
      { path: "nested/binary.bin", bytes: Buffer.from([0, 1, 2, 10, 13, 255]) },
      { path: "unicode/π.txt", bytes: Buffer.from("π🙂\n") },
    ];
    const manifest = makeManifest(files);
    const validation = validateManifest(manifest);
    equal(validation.files, files.length, "manifest file count");
    const dest = join(base, "out");
    const installed = await installVerifiedArtifacts(dest, manifest);
    check(installed.committed && installed.verified, "verified artifact install did not commit");
    for (const f of files) {
      const actual = await readFile(join(dest, f.path));
      check(actual.equals(f.bytes), `artifact bytes changed: ${f.path}`);
    }
    await rejects(() => installVerifiedArtifacts(dest, manifest), /already exists/i, "existing destination overwritten");

    const badCases = [];
    const traversal = makeManifest([{ path: "safe.txt", bytes: Buffer.from("x") }]);
    traversal.files[0].path = "../../escape.txt";
    traversal.manifest_sha256 = manifestSha256(traversal);
    badCases.push(traversal);
    const mismatch = makeManifest([{ path: "x.txt", bytes: Buffer.from("x") }]);
    mismatch.files[0].sha256 = "0".repeat(64);
    mismatch.manifest_sha256 = manifestSha256(mismatch);
    badCases.push(mismatch);
    const collision = makeManifest([{ path: "A.txt", bytes: Buffer.from("a") }, { path: "a.TXT", bytes: Buffer.from("b") }]);
    badCases.push(collision);
    const treeCollision = makeManifest([{ path: "a", bytes: Buffer.from("a") }, { path: "a/b", bytes: Buffer.from("b") }]);
    badCases.push(treeCollision);
    const incomplete = makeManifest([{ path: "x", bytes: Buffer.from("x") }]);
    incomplete.complete = false;
    incomplete.manifest_sha256 = manifestSha256(incomplete);
    badCases.push(incomplete);
    for (let i = 0; i < badCases.length; i++) {
      throws(() => validateManifest(badCases[i]), /rejected|mismatch|collision|incomplete|unsafe/i, `bad manifest ${i} accepted`);
    }

    const symlinkTarget = join(base, "real-parent");
    await mkdir(symlinkTarget);
    const link = join(base, "linked-parent");
    try {
      await symlink(symlinkTarget, link, "dir");
      await rejects(() => installVerifiedArtifacts(join(link, "out"), makeManifest([{ path: "x", bytes: Buffer.from("x") }])),
        /symbolic-link/i, "symlink ancestor accepted");
    } catch (error) {
      if (!["EPERM", "EACCES", "ENOSYS"].includes(error?.code)) throw error;
    }
  } finally {
    await rm(base, { recursive: true, force: true });
  }
}

function streamFromChunks(chunks) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(Buffer.from(chunk));
      controller.close();
    },
  });
}

async function parseEvents(chunks) {
  const events = [];
  for await (const event of parseSSEStream(streamFromChunks(chunks))) events.push(event);
  return events;
}

async function sseCampaign() {
  const variants = [
    "event: run_done\ndata: {\"ok\":true}\n\n",
    "event:run_done\ndata:{\"ok\":true}\n\n",
    "event: run_done\r\ndata: {\"ok\":true}\r\n\r\n",
    "event: run_done\rdata: {\"ok\":true}\r\r",
    ": comment\nevent: run_done\ndata: {\"ok\":true}\n\n",
    "event: run_done\ndata: {\"ok\":true}\n",
  ];
  for (const raw of variants) {
    const events = await parseEvents([raw]);
    equal(events.length, 1, `SSE variant did not dispatch: ${JSON.stringify(raw)}`);
    equal(events[0].event, "run_done", "SSE event name");
    check(events[0].data?.ok === true, "SSE JSON payload lost");
  }

  const raw = "event: token\ndata: {\"token\":\"π🙂\"}\n\nevent: run_done\ndata: {\"ok\":true}\n\n";
  for (let size = 1; size <= raw.length; size++) {
    const chunks = [];
    for (let i = 0; i < raw.length; i += size) chunks.push(raw.slice(i, i + size));
    const events = await parseEvents(chunks);
    equal(events.length, 2, `chunk size ${size} lost events`);
    equal(events[0].data.token, "π🙂", `chunk size ${size} corrupted UTF-8`);
  }

  const multiline = "event: note\ndata: first\ndata: second\n\n";
  const events = await parseEvents([multiline]);
  equal(events[0].data, "first\nsecond", "multiline SSE data not joined");
}

function runCli(args, options = {}) {
  return spawnSync(process.execPath, [BIN, ...args], { encoding: "utf8", timeout: 15000, ...options });
}

async function runCliAsync(args, options = {}) {
  return await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(process.execPath, [BIN, ...args], { stdio: ["ignore", "pipe", "pipe"], ...options });
    let stdout = ""; let stderr = "";
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stderr += d; });
    const timer = setTimeout(() => { child.kill("SIGKILL"); rejectPromise(new Error("CLI timed out")); }, 20000);
    child.on("error", rejectPromise);
    child.on("close", (code, signal) => { clearTimeout(timer); resolvePromise({ code, signal, stdout, stderr }); });
  });
}

async function cliCampaign() {
  let r = runCli(["--version"]);
  equal(r.status, 0, "--version exit");
  check(/^0\.3\.0-beta\.1\s*$/.test(r.stdout), `unexpected version ${r.stdout}`);
  r = runCli(["--help"]);
  equal(r.status, 0, "--help exit");
  check(r.stdout.includes("USAGE"), "help missing USAGE");

  const usageCases = [
    ["frobnicate"], ["code"], ["ask"], ["status", "--nope"],
    ["code", "x", "--max-steps"], ["code", "x", "--max-steps", "NaN"],
    ["code", "x", "--max-steps", "0"], ["receipts", "--limit", "-1"],
    ["status", "--base", "http://example.com"], ["status", "--save", "x"],
  ];
  for (const args of usageCases) {
    r = runCli(args);
    equal(r.status, 2, `usage case should exit 2: ${args.join(" ")}`);
  }

  const server = createServer((req, res) => {
    if (req.url === "/api/demo/status") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ model_ready: true, runs_completed: 1, runs_started: 1, replays: 0, limits: {} }));
      return;
    }
    if (req.url?.startsWith("/api/demo/code/receipts")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ receipts: [{ receipt_sha: "abc", verdict: "broken", task: "safe\u001b]52;c;YmFk\u0007task" }], stats: {} }));
      return;
    }
    if (req.url === "/api/demo/code/run") {
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.end("event: code_done\ndata: {\"ok\":true,\"run_id\":\"missing-receipt\"}\n\n");
      return;
    }
    res.writeHead(404); res.end();
  });
  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  const port = server.address().port;
  const base = `http://127.0.0.1:${port}`;
  try {
    let out = await runCliAsync(["status", "--base", base, "--json"]);
    equal(out.code, 0, `mock status failed: ${out.stderr}`);
    const parsed = JSON.parse(out.stdout);
    check(parsed.model_ready === true, "mock status JSON wrong");
    equal(out.stdout.trim().split("\n").length, 1, "status emitted multiple JSON documents");

    out = await runCliAsync(["code", "test missing receipt", "--base", base, "--json"]);
    equal(out.code, 1, "missing receipt code run exited success");
    const failed = JSON.parse(out.stdout);
    check(failed.ok === false, "missing receipt JSON reported ok");
    equal(out.stdout.trim().split("\n").length, 1, "failed code emitted multiple JSON documents");

    out = await runCliAsync(["receipts", "--base", base]);
    equal(out.code, 0, "receipts mock failed");
    check(!out.stdout.includes("\u001b") && !out.stdout.includes("\u0007"), "terminal escape survived receipt rendering");
  } finally {
    await new Promise((resolvePromise) => server.close(resolvePromise));
  }
}

await pathCampaign();
verdictTruthTable();
receiptCampaign();
terminalCampaign();
await artifactCampaign();
await sseCampaign();
await cliCampaign();

console.log(JSON.stringify({ ok: true, checks, suite: "veyretest-cli-independent", node: process.version }));
