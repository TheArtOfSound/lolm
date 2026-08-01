// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * CLI safety + correctness tests.
 *   node test/run.mjs
 */
import { execFile } from "node:child_process";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import assert from "node:assert/strict";
import { mkdtemp, writeFile, readFile, access, mkdir, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { applyUnifiedDiff, replayFileChanges } from "../lib/diff.mjs";
import { safeDestination, isSafeUnder } from "../lib/paths.mjs";
import { evaluateShipped } from "../lib/shipped.mjs";
import { createHash, generateKeyPairSync, sign as cryptoSign } from "node:crypto";
import { verifyCodeReceipt, pyStyleDumps, sha256Short, extractSealedCore } from "../lib/receipt.mjs";
import { installVerifiedArtifacts, manifestSha256, validateManifest } from "../lib/artifacts.mjs";

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const BIN = join(here, "..", "bin", "lolm.mjs");

let pass = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

async function withServer(handler, fn) {
  const server = createServer(handler);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const { port } = server.address();
  try {
    return await fn(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

function jsonResponse(res, value, status = 200) {
  const body = JSON.stringify(value);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
  res.end(body);
}

function signedReceipt(core, privateKey, keyId = "test-key") {
  const blob = pyStyleDumps(core);
  return {
    ...core,
    receipt_sha: createHash("sha256").update(blob).digest("hex"),
    signature: {
      alg: "Ed25519", key_id: keyId,
      sig: cryptoSign(null, Buffer.from(blob), privateKey).toString("base64url"),
    },
  };
}

function rawPublicKey(publicKey) {
  const der = publicKey.export({ type: "spki", format: "der" });
  return der.subarray(der.length - 32).toString("base64url");
}

// ── path containment ─────────────────────────────────────────────────────────

test("safeDestination rejects path traversal", () => {
  const root = "/tmp/lolm-output";
  assert.throws(() => safeDestination(root, "../../tmp/lolm-escaped.txt"), /escaped|absolute/);
  assert.throws(() => safeDestination(root, "/etc/passwd"), /absolute/);
  assert.throws(() => safeDestination(root, ".."), /escaped|unsafe/);
  assert.throws(() => safeDestination(root, "foo/../../../etc/passwd"), /escaped|unsafe/);
  const ok = safeDestination(root, "src/solution.py");
  assert.ok(ok.endsWith("src/solution.py") || ok.includes("solution.py"));
  assert.equal(isSafeUnder(root, "ok.py"), true);
  assert.equal(isSafeUnder(root, "../x"), false);
});

test("artifact paths reject absolute, traversal, NUL, empty, and platform-reserved forms", () => {
  const root = "/tmp/lolm-output";
  for (const path of [
    "../x", "..\\x", "/etc/passwd", "C:\\Windows\\x", "\\\\server\\share\\x",
    "a\0b", "a//b", "a/./b", "CON", "aux.txt", "trail. ",
  ]) assert.throws(() => safeDestination(root, path), undefined, path);
});

test("transactional artifact install preserves exact bytes and verifies hashes", async () => {
  const root = await mkdtemp(join(tmpdir(), "lolm-artifact-"));
  const dest = join(root, "out");
  const content = Buffer.from("no final newline", "utf8");
  const manifest = {
    schema: "lolm.artifact.manifest.v1", run_id: "run_1", artifact_id: "art_1", complete: true,
    files: [{ path: "src/a.txt", type: "file", size: content.length,
      sha256: sha256Short(content.toString(), 64), encoding: "base64",
      content_base64: content.toString("base64"), executable: false }],
  };
  manifest.manifest_sha256 = manifestSha256(manifest);
  const result = await installVerifiedArtifacts(dest, manifest);
  assert.equal(result.verified, true, JSON.stringify(result));
  assert.deepEqual(await readFile(join(dest, "src/a.txt")), content);
});

test("artifact install rejects symlinks, mismatches, collisions, and existing destinations atomically", async () => {
  const root = await mkdtemp(join(tmpdir(), "lolm-artifact-adversarial-"));
  const outside = join(root, "outside");
  await mkdir(outside);
  const linkedDest = join(root, "linked");
  await symlink(outside, linkedDest, "dir");
  const content = Buffer.from("safe");
  const base = {
    schema: "lolm.artifact.manifest.v1", run_id: "run_1", artifact_id: "art_1", complete: true,
    files: [{ path: "a.txt", type: "file", size: content.length,
      sha256: sha256Short(content.toString(), 64), encoding: "base64",
      content_base64: content.toString("base64"), executable: false }],
  };
  base.manifest_sha256 = manifestSha256(base);
  await assert.rejects(() => installVerifiedArtifacts(linkedDest, base), /exist|symbolic|symlink/i);
  await assert.rejects(access(join(outside, "a.txt")));

  const bad = structuredClone(base);
  bad.files[0].sha256 = "0".repeat(64);
  bad.manifest_sha256 = manifestSha256(bad);
  const badDest = join(root, "bad");
  await assert.rejects(() => installVerifiedArtifacts(badDest, bad), /hash/i);
  await assert.rejects(access(badDest));

  assert.throws(() => validateManifest({ ...base, files: [
    base.files[0], { ...base.files[0], path: "A.TXT" },
  ] }), /duplicate|collision/i);

  const existing = join(root, "existing");
  await mkdir(existing);
  await writeFile(join(existing, "keep.txt"), "keep");
  await assert.rejects(() => installVerifiedArtifacts(existing, base), /exists/i);
  assert.equal(await readFile(join(existing, "keep.txt"), "utf8"), "keep");
});

// ── shipped fail-closed ──────────────────────────────────────────────────────

test("shipped never true when verdict is broken", () => {
  const r = evaluateShipped(
    { ok: true },
    { verdict: "broken", ok: false, syntax_ok: true, files: [] },
  );
  assert.equal(r.shipped, false);
});

test("shipped false when receipt missing", () => {
  assert.equal(evaluateShipped({ ok: true }, null).shipped, false);
  assert.equal(evaluateShipped({ ok: true }, {}).shipped, false);
});

test("shipped requires explicit shipped+ok", () => {
  assert.equal(evaluateShipped(
    { ok: true, run_id: "run_1" },
    { schema: "lolm.code.receipt.v2", run_id: "run_1", verdict: "shipped", ok: true, syntax_ok: true,
      verification: { syntax_ok: true, execution_ok: true, contract_ok: true,
        artifact_manifest_ok: true },
      files: ["a.py"], green_runs: 1 },
    { receiptVerified: true },
  ).shipped, true);
  assert.equal(evaluateShipped(
    { ok: false, run_id: "run_1" },
    { schema: "lolm.code.receipt.v2", run_id: "run_1", verdict: "shipped", ok: true, syntax_ok: true,
      verification: { syntax_ok: true, execution_ok: true, contract_ok: true,
        artifact_manifest_ok: true } },
    { receiptVerified: true },
  ).shipped, false);
  assert.equal(evaluateShipped(
    { ok: true },
    { verdict: "shipped", ok: true, syntax_ok: false, files: ["a.py"] },
  ).shipped, false);
});

test("shipped fails closed for every missing or contradictory receipt field", () => {
  const good = {
    schema: "lolm.code.receipt.v2", run_id: "run_1", verdict: "shipped", ok: true,
    syntax_ok: true,
    verification: { syntax_ok: true, execution_ok: true, contract_ok: true,
      artifact_manifest_ok: true },
  };
  assert.equal(evaluateShipped({ ok: true, run_id: "run_1" }, good, { receiptVerified: true }).shipped, true);
  for (const mutate of [
    (r) => { delete r.schema; }, (r) => { delete r.run_id; },
    (r) => { r.verdict = "incomplete"; }, (r) => { r.ok = false; },
    (r) => { r.syntax_ok = false; }, (r) => { delete r.verification.execution_ok; },
    (r) => { r.verification.contract_ok = false; },
    (r) => { r.verification.artifact_manifest_ok = false; },
  ]) {
    const receipt = structuredClone(good);
    mutate(receipt);
    assert.equal(evaluateShipped({ ok: true, run_id: "run_1" }, receipt, { receiptVerified: true }).shipped, false, JSON.stringify(receipt));
  }
  assert.equal(evaluateShipped({ ok: true, run_id: "other" }, good, { receiptVerified: true }).shipped, false);
  assert.equal(evaluateShipped({ ok: true, run_id: "run_1" }, good, { receiptVerified: false }).shipped, false);
});

// ── diff / newline ───────────────────────────────────────────────────────────

test("creates a new file from a creation hunk", () => {
  const diff = [
    "--- a/solution.py", "+++ b/solution.py", "@@ -0,0 +1,3 @@",
    "+def f():", "+    return 42", "+print(f())", "",
  ].join("\n");
  const r = applyUnifiedDiff("", diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "def f():\n    return 42\nprint(f())\n");
});

test("applies an edit against matching context", () => {
  const before = "def f():\n    return 41\nprint(f())\n";
  const diff = [
    "--- a/s.py", "+++ b/s.py", "@@ -1,3 +1,3 @@",
    " def f():", "-    return 41", "+    return 42", " print(f())", "",
  ].join("\n");
  const r = applyUnifiedDiff(before, diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "def f():\n    return 42\nprint(f())\n");
});

test("preserves absence of trailing newline", () => {
  const before = "a\nb"; // no final \n
  const diff = ["@@ -1,2 +1,2 @@", " a", "-b", "+B", ""].join("\n");
  const r = applyUnifiedDiff(before, diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "a\nB");
  assert.equal(r.text.endsWith("\n"), false);
});

test("preserves presence of trailing newline", () => {
  const before = "a\nb\n";
  const diff = ["@@ -1,2 +1,2 @@", " a", "-b", "+B", ""].join("\n");
  const r = applyUnifiedDiff(before, diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "a\nB\n");
});

test("refuses a diff whose context does not match", () => {
  const diff = [
    "--- a/s.py", "+++ b/s.py", "@@ -1,2 +1,2 @@",
    " def g():", "-    return 1", "+    return 2", "",
  ].join("\n");
  const r = applyUnifiedDiff("def f():\n    return 1\n", diff);
  assert.equal(r.ok, false);
  assert.match(r.reason, /context mismatch/);
});

test("refuses a truncated diff instead of half-applying it", () => {
  const diff = [
    "--- a/s.py", "+++ b/s.py", "@@ -0,0 +1,5 @@",
    "+line one", "+line two",
  ].join("\n");
  const r = applyUnifiedDiff("", diff);
  assert.equal(r.ok, false);
  assert.match(r.reason, /truncated|incomplete/);
});

test("refuses garbage and empty input", () => {
  assert.equal(applyUnifiedDiff("", "").ok, false);
  assert.equal(applyUnifiedDiff("", "not a diff at all").ok, false);
  assert.match(applyUnifiedDiff("", "not a diff at all").reason, /no hunks/);
});

test("preserves lines after the final hunk", () => {
  const before = "a\nb\nc\nd\n";
  const diff = ["@@ -1,2 +1,2 @@", " a", "-b", "+B", ""].join("\n");
  const r = applyUnifiedDiff(before, diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "a\nB\nc\nd\n");
});

test("replays create-then-edit into the final content", () => {
  const create = ["@@ -0,0 +1,2 @@", "+x = 1", "+print(x)", ""].join("\n");
  const edit = ["@@ -1,2 +1,2 @@", "-x = 1", "+x = 2", " print(x)", ""].join("\n");
  const { files, failed } = replayFileChanges([
    { path: "a.py", diff: create },
    { path: "a.py", diff: edit },
  ]);
  assert.equal(failed.size, 0);
  assert.equal(files.get("a.py"), "x = 2\nprint(x)\n");
});

test("a failed file is reported, not written with partial content", () => {
  const create = ["@@ -0,0 +1,1 @@", "+ok = 1", ""].join("\n");
  const bad = ["@@ -0,0 +1,9 @@", "+only one line"].join("\n");
  const { files, failed } = replayFileChanges([
    { path: "good.py", diff: create },
    { path: "bad.py", diff: bad },
  ]);
  assert.equal(files.has("good.py"), true);
  assert.equal(files.has("bad.py"), false);
  assert.equal(failed.has("bad.py"), true);
});

test("once a file fails, later diffs for it stay rejected", () => {
  const bad = ["@@ -0,0 +1,9 @@", "+one"].join("\n");
  const create = ["@@ -0,0 +1,1 @@", "+x = 1", ""].join("\n");
  const { files, failed } = replayFileChanges([
    { path: "f.py", diff: bad },
    { path: "f.py", diff: create },
  ]);
  assert.equal(files.has("f.py"), false);
  assert.equal(failed.has("f.py"), true);
});

// ── receipt verify ───────────────────────────────────────────────────────────

test("verifyCodeReceipt recomputes sha over sealed core", () => {
  const core = {
    kind: "code_agent",
    task: "print 42",
    summary: "ok",
    ts: 1,
    steps: 1,
    ran: true,
    produced_output: true,
    stuck: false,
    budget_hit: false,
    error: "",
    files: ["hello.py"],
    green_runs: 1,
    failed_runs: 0,
    verifies: 0,
    expected: ["42"],
    expected_ok: true,
    missing_expected: [],
    last_stdout_tail: "42",
    trail: [],
    syntax_ok: true,
    syntax_error: "",
    syntax_checked: ["hello.py"],
    ok: true,
    visual_missing_html: false,
  };
  const sha = sha256Short(pyStyleDumps(core), 24);
  const receipt = { ...core, receipt_sha: sha, verdict: "shipped" };
  const v = verifyCodeReceipt(receipt);
  assert.equal(v.receipt_hash_match, true, JSON.stringify(v));
  assert.equal(v.shipped_allowed, false, "legacy receipts cannot authorize shipping");
  assert.equal(v.integrity.verified, false, "unsigned legacy receipts are not independently verified");
});

test("verifyCodeReceipt validates a signed v2 receipt and rejects tampering", () => {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const core = {
    schema: "lolm.code.receipt.v2",
    run_id: "run_123",
    kind: "code_agent",
    task: "print 42",
    verdict: "shipped",
    ok: true,
    syntax_ok: true,
    verification: {
      syntax_ok: true,
      execution_ok: true,
      contract_ok: true,
      artifact_manifest_ok: true,
      artifact_manifest_sha256: "a".repeat(64),
    },
  };
  const blob = pyStyleDumps(core);
  const receipt = {
    ...core,
    receipt_sha: sha256Short(blob, 64),
    signature: {
      alg: "Ed25519",
      key_id: "test-key",
      sig: cryptoSign(null, Buffer.from(blob), privateKey).toString("base64url"),
    },
  };
  const publicKeys = { "test-key": publicKey.export({ type: "spki", format: "pem" }) };
  const verified = verifyCodeReceipt(receipt, { publicKeys });
  assert.equal(verified.integrity.verified, true, JSON.stringify(verified));
  const tampered = structuredClone(receipt);
  tampered.verification.contract_ok = false;
  assert.equal(verifyCodeReceipt(tampered, { publicKeys }).integrity.verified, false);
});

test("verifyCodeReceipt detects tampering", () => {
  const receipt = {
    kind: "code_agent",
    task: "x",
    ok: true,
    verdict: "shipped",
    syntax_ok: true,
    files: [],
    trail: [],
    receipt_sha: "deadbeefdeadbeefdeadbeef",
  };
  const v = verifyCodeReceipt(receipt);
  assert.equal(v.receipt_hash_match, false);
  assert.equal(v.integrity.verified, false);
});

// ── binary ───────────────────────────────────────────────────────────────────

test("--version prints just the version", async () => {
  const { stdout } = await run(process.execPath, [BIN, "--version"]);
  assert.match(stdout.trim(), /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/);
});

test("--help lists the commands", async () => {
  const { stdout } = await run(process.execPath, [BIN, "--help"]);
  for (const cmd of ["code", "ask", "build", "receipts", "status", "memory", "doctor", "receipt"]) {
    assert.ok(stdout.includes(cmd), `help should mention ${cmd}`);
  }
});

test("no args prints starter rather than erroring", async () => {
  const { stdout } = await run(process.execPath, [BIN]);
  assert.ok(stdout.includes("lolm") || stdout.includes("Next"));
});

test("an unknown command exits 2 with a usable message", async () => {
  await assert.rejects(
    run(process.execPath, [BIN, "frobnicate"]),
    (e) => e.code === 2 && /unknown command/.test(e.stderr),
  );
});

test("code with no task exits 2 instead of calling the API", async () => {
  await assert.rejects(
    run(process.execPath, [BIN, "code"]),
    (e) => e.code === 2 && /what should it build/.test(e.stderr),
  );
});

test("an unknown flag exits 2", async () => {
  await assert.rejects(
    run(process.execPath, [BIN, "status", "--nope"]),
    (e) => e.code === 2 && /unknown flag/.test(e.stderr),
  );
});

test("missing option values and invalid numeric bounds exit 2 before network", async () => {
  for (const args of [
    ["status", "--base"],
    ["code", "task", "--save", "--json"],
    ["code", "task", "--max-steps", "abc"],
    ["code", "task", "--max-steps", "0"],
    ["code", "task", "--max-steps", "1.5"],
    ["receipts", "--limit", "999999999999999999999"],
  ]) {
    await assert.rejects(
      run(process.execPath, [BIN, ...args]),
      (e) => e.code === 2 && /error|usage|must|value/i.test(e.stderr || e.stdout),
      args.join(" "),
    );
  }
});

test("base URL accepts HTTPS and loopback HTTP but rejects unsafe origins", async () => {
  for (const base of ["file:///tmp/x", "http://example.com", "https://user:pass@example.com", "not a url"] ) {
    await assert.rejects(
      run(process.execPath, [BIN, "status", "--base", base]),
      (e) => e.code === 2,
      base,
    );
  }
});

test("-- sentinel preserves option-looking prompt text", async () => {
  await withServer((req, res) => {
    if (req.url === "/api/demo/run/stream") {
      let body = "";
      req.on("data", (chunk) => { body += chunk; });
      req.on("end", () => {
        const command = JSON.parse(body).command;
        const sse = `event: run_done\ndata: ${JSON.stringify({ ended_by: "natural_eos", answer: command })}\n\n`;
        res.writeHead(200, { "Content-Type": "text/event-stream" });
        res.end(sse);
      });
      return;
    }
    jsonResponse(res, { error: "not found" }, 404);
  }, async (base) => {
    const { stdout } = await run(process.execPath, [BIN, "ask", "--base", base, "--json", "--", "explain", "--help"]);
    const result = JSON.parse(stdout);
    assert.equal(result.result.answer, "explain --help");
  });
});

test("JSON mode emits one complete document and drains large output", async () => {
  await withServer((req, res) => {
    if (req.url === "/api/demo/status") return jsonResponse(res, {
      model_ready: true, busy: false, runs_completed: 1, runs_started: 1,
      replays: 0, large: "x".repeat(1024 * 1024),
    });
    if (req.url === "/api/demo/billing/usage") return jsonResponse(res, {});
    jsonResponse(res, { error: "not found" }, 404);
  }, async (base) => {
    const { stdout } = await run(process.execPath, [BIN, "status", "--base", base, "--json"], { maxBuffer: 3 * 1024 * 1024 });
    const parsed = JSON.parse(stdout);
    assert.equal(parsed.large.length, 1024 * 1024);
    assert.equal(stdout.trim().split("\n").length, 1);
  });
});

test("timeout exits 124 with one typed JSON error", async () => {
  await withServer((_req, _res) => { /* intentionally never respond */ }, async (base) => {
    await assert.rejects(
      run(process.execPath, [BIN, "status", "--base", base, "--timeout", "20", "--json"], { timeout: 3000 }),
      (e) => {
        assert.equal(e.code, 124);
        const doc = JSON.parse(e.stdout);
        return doc.error.code === "TIMEOUT" && e.stdout.trim().split("\n").length === 1;
      },
    );
  });
});

test("human output strips ANSI, OSC, C0, and bidi controls", async () => {
  await withServer((req, res) => {
    if (req.url === "/api/demo/run/stream") {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.end(
        'event: token\ndata: {"token":"\\u001b]52;c;UFdO\\u0007\\u001b[31mred\\u001b[0m\\rforged\\u202e","channel":"final"}\n\n' +
        'event: run_done\ndata: {"ended_by":"natural_eos"}\n\n',
      );
      return;
    }
    jsonResponse(res, { error: "not found" }, 404);
  }, async (base) => {
    const { stdout, stderr } = await run(process.execPath, [BIN, "ask", "test", "--base", base]);
    const text = stdout + stderr;
    assert.equal(/[\u001b\u0007\u000d\u202e]/u.test(text), false, JSON.stringify(text));
    assert.match(text, /redforged/);
  });
});

test("code --save --json commits only a signed, hash-bound exact artifact", async () => {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const content = "exact bytes without newline";
  const file = { path: "src/result.txt", type: "file", size: Buffer.byteLength(content),
    sha256: createHash("sha256").update(content).digest("hex"), encoding: "utf-8",
    content, executable: false };
  const manifest = { schema: "lolm.artifact.manifest.v1", run_id: "run_1",
    artifact_id: "art_1", complete: true, files: [file] };
  manifest.manifest_sha256 = manifestSha256(manifest);
  const receipt = signedReceipt({
    schema: "lolm.code.receipt.v2", run_id: "run_1", kind: "code_agent",
    task: "x", verdict: "shipped", ok: true, syntax_ok: true,
    verification: { syntax_ok: true, execution_ok: true, contract_ok: true,
      artifact_manifest_ok: true,
      artifact_manifest_sha256: manifest.manifest_sha256 },
  }, privateKey);
  await withServer((req, res) => {
    if (req.url === "/api/demo/receipts/keys") return jsonResponse(res, {
      schema: "lolm.receipt.keys.v1",
      keys: [{ key_id: "test-key", alg: "Ed25519", public_key: rawPublicKey(publicKey) }],
    });
    if (req.url === "/api/demo/code/run") {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.end(
        `event: artifact_manifest\ndata: ${JSON.stringify(manifest)}\n\n` +
        'event: code_done\ndata: {"ok":true,"run_id":"run_1","summary":"done"}\n\n' +
        `event: code_receipt\ndata: ${JSON.stringify(receipt)}\n\n`,
      );
      return;
    }
    jsonResponse(res, { error: "not found" }, 404);
  }, async (base) => {
    const root = await mkdtemp(join(tmpdir(), "lolm-code-save-"));
    const dest = join(root, "out");
    const { stdout } = await run(process.execPath, [BIN, "code", "x", "--base", base,
      "--save", dest, "--json"]);
    const result = JSON.parse(stdout);
    assert.equal(result.ok, true, stdout);
    assert.equal(result.saved.verified, true);
    assert.equal(await readFile(join(dest, "src/result.txt"), "utf8"), content);
  });
});

test("hostile or unverified save responses exit nonzero and write nothing", async () => {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const escapedName = `escaped-${Date.now()}.txt`;
  const content = "pwn";
  const manifest = { schema: "lolm.artifact.manifest.v1", run_id: "run_bad",
    artifact_id: "art_bad", complete: true, files: [{ path: `../../${escapedName}`, type: "file",
      size: 3, sha256: createHash("sha256").update(content).digest("hex"),
      encoding: "utf-8", content, executable: false }] };
  manifest.manifest_sha256 = manifestSha256(manifest);
  const receipt = signedReceipt({
    schema: "lolm.code.receipt.v2", run_id: "run_bad", kind: "code_agent",
    task: "x", verdict: "shipped", ok: true, syntax_ok: true,
    verification: { syntax_ok: true, execution_ok: true, contract_ok: true,
      artifact_manifest_ok: true,
      artifact_manifest_sha256: manifest.manifest_sha256 },
  }, privateKey);
  await withServer((req, res) => {
    if (req.url === "/api/demo/receipts/keys") return jsonResponse(res, {
      keys: [{ key_id: "test-key", alg: "Ed25519", public_key: rawPublicKey(publicKey) }],
    });
    if (req.url === "/api/demo/code/run") {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.end(`event: artifact_manifest\ndata: ${JSON.stringify(manifest)}\n\n` +
        'event: code_done\ndata: {"ok":true,"run_id":"run_bad"}\n\n' +
        `event: code_receipt\ndata: ${JSON.stringify(receipt)}\n\n`);
      return;
    }
    jsonResponse(res, { error: "not found" }, 404);
  }, async (base) => {
    const root = await mkdtemp(join(tmpdir(), "lolm-code-hostile-"));
    const dest = join(root, "out");
    await assert.rejects(
      run(process.execPath, [BIN, "code", "x", "--base", base, "--save", dest, "--json"]),
      (e) => e.code === 1 && JSON.parse(e.stdout).saved.committed === false,
    );
    await assert.rejects(access(dest));
    await assert.rejects(access(join(root, "..", "..", escapedName)));
  });
});

test("build commits HTML only after local receipt and content-hash verification", async () => {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const html = "<!DOCTYPE html><html><body>verified</body></html>";
  const htmlSha = createHash("sha256").update(html).digest("hex");
  const goodReceipt = signedReceipt({
    schema: "lolm.visual.receipt.v2", run_id: "visual_1", kind: "visual_build",
    task: "page", verdict: "verified", ok: true,
    verification: { browser_ok: true, html_sha256: htmlSha,
      byte_count: Buffer.byteLength(html) },
  }, privateKey);
  let receipt = goodReceipt;
  await withServer((req, res) => {
    if (req.url === "/api/demo/receipts/keys") return jsonResponse(res, {
      keys: [{ key_id: "test-key", alg: "Ed25519", public_key: rawPublicKey(publicKey) }],
    });
    if (req.url === "/api/demo/code/visual/build") {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.end(`event: done\ndata: ${JSON.stringify({ html, bytes: Buffer.byteLength(html), verified: true, run_id: "visual_1" })}\n\n` +
        `event: visual_receipt\ndata: ${JSON.stringify(receipt)}\n\n`);
      return;
    }
    jsonResponse(res, { error: "not found" }, 404);
  }, async (base) => {
    const root = await mkdtemp(join(tmpdir(), "lolm-build-"));
    const goodPath = join(root, "good.html");
    const { stdout } = await run(process.execPath, [BIN, "build", "page", "--base", base,
      "--out", goodPath, "--json"]);
    assert.equal(JSON.parse(stdout).ok, true);
    assert.equal(await readFile(goodPath, "utf8"), html);

    receipt = structuredClone(goodReceipt);
    receipt.verification.browser_ok = false;
    const badPath = join(root, "bad.html");
    await assert.rejects(
      run(process.execPath, [BIN, "build", "page", "--base", base,
        "--out", badPath, "--json"]),
      (e) => e.code === 1 && JSON.parse(e.stdout).error.code === "RECEIPT_VERIFICATION_FAILED",
    );
    await assert.rejects(access(badPath));
  });
});

test("receipt verify on a hand-built file reports mismatch", async () => {
  const dir = await mkdtemp(join(tmpdir(), "lolm-rcpt-"));
  const path = join(dir, "r.json");
  await writeFile(path, JSON.stringify({
    kind: "code_agent", task: "t", ok: true, verdict: "shipped",
    syntax_ok: true, files: [], trail: [], receipt_sha: "0".repeat(24),
  }));
  await assert.rejects(
    run(process.execPath, [BIN, "receipt", "verify", path]),
    (e) => e.code === 1,
  );
});

test("doctor runs offline checks without requiring network success", async () => {
  // may fail api_status if offline — still exits and prints
  try {
    const { stdout, stderr } = await run(process.execPath, [BIN, "doctor", "--base", "http://127.0.0.1:9"], {
      timeout: 8000,
    });
    const text = stdout + stderr;
    assert.ok(/path_containment|doctor|PASS|ISSUES/i.test(text));
  } catch (e) {
    // exit 1 is ok if API unreachable
    const text = (e.stdout || "") + (e.stderr || "");
    assert.ok(/path_containment|doctor|ISSUES|✓|✗/i.test(text), text);
  }
});

// ── run ─────────────────────────────────────────────────────────────────────

for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`  ✓ ${name}`);
    pass++;
  } catch (e) {
    console.error(`  ✗ ${name}\n    ${e.message}`);
    process.exitCode = 1;
  }
}
console.log(`\n${pass}/${tests.length} passed`);
