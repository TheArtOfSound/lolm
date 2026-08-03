// Copyright (c) 2026 Qira LLC. All rights reserved.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const BIN = join(here, "..", "bin", "lolm-delivery.mjs");

let passed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

async function context(name) {
  const root = await mkdtemp(join(tmpdir(), `lolm-continuity-receipt-${name}-`));
  return {
    root,
    ledger: join(root, "continuity.json"),
    sessions: join(root, "sessions"),
    fakeCore: join(root, "fake-core.mjs"),
  };
}

test("sealed core receipt populates receipt, manifest, artifact ID, and exact hashes", async () => {
  const ctx = await context("binding");
  const receiptSha = "a".repeat(64);
  const manifestSha = "b".repeat(64);
  await writeFile(ctx.fakeCore, [
    `import { mkdir, writeFile } from 'node:fs/promises';`,
    `import { join } from 'node:path';`,
    `const args = process.argv.slice(2);`,
    `const value = (flag) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : ''; };`,
    `const save = value('--save');`,
    `const receipt = value('--receipt');`,
    `await mkdir(save, { recursive: true });`,
    `await writeFile(join(save, 'output.pdf'), Buffer.from('%PDF-1.4\\nsealed continuity\\n%%EOF\\n'));`,
    `await writeFile(receipt, JSON.stringify({`,
    `  verdict: 'shipped',`,
    `  receipt_sha: ${JSON.stringify(receiptSha)},`,
    `  run_id: 'run_receipt_binding',`,
    `  task_state: { task_id: 'task_receipt_binding' },`,
    `  verification: { artifact_manifest_sha256: ${JSON.stringify(manifestSha)} },`,
    `  files: ['output.pdf']`,
    `}, null, 2));`,
    `process.stdout.write('verdict   shipped\\nreceipt   ${receiptSha}  hash ok\\ntask      task_receipt_binding\\n');`,
  ].join("\n"));

  const env = {
    ...process.env,
    HOME: ctx.root,
    USERPROFILE: ctx.root,
    LOLM_CONTINUITY_LEDGER: ctx.ledger,
    LOLM_SESSION_DIR: ctx.sessions,
    LOLM_CORE_CLI: ctx.fakeCore,
    NO_COLOR: "1",
  };
  const generated = await run(process.execPath, [
    BIN,
    "code",
    "Create a valid PDF report",
    "--base",
    "https://127.0.0.1.invalid",
  ], { env, timeout: 30_000 });
  assert.match(generated.stdout, /delivered pdf/);
  assert.match(generated.stdout, /saved\s+.*output\.pdf/);
  assert.doesNotMatch(generated.stdout + generated.stderr, /ENOTFOUND|fetch failed/);

  const inspected = await run(process.execPath, [
    BIN,
    "artifact",
    "inspect",
    "pdf",
    "--json",
  ], { env, timeout: 15_000 });
  const payload = JSON.parse(inspected.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.record.receipt_sha, receiptSha);
  assert.equal(payload.record.manifest_sha, manifestSha);
  assert.equal(payload.record.run_id, "run_receipt_binding");
  assert.equal(payload.record.task_id, "task_receipt_binding");
  assert.equal(payload.record.fully_verified, true);
  assert.match(payload.record.artifact_ids[0], /^artifact_[a-f0-9]{24}$/);
  assert.equal(payload.record.intact[0].sha256, payload.record.intact[0].current_sha256);
  assert.equal(payload.record.intact[0].verified, true);

  const ledger = JSON.parse(await readFile(ctx.ledger, "utf8"));
  assert.equal(ledger.records.length, 1);
  assert.equal(ledger.records[0].manifest_sha, manifestSha);
});

test("JSON-mode local failures emit one stdout document and no stderr payload", async () => {
  const ctx = await context("json-failure");
  const env = {
    ...process.env,
    HOME: ctx.root,
    USERPROFILE: ctx.root,
    LOLM_CONTINUITY_LEDGER: ctx.ledger,
    LOLM_SESSION_DIR: ctx.sessions,
    NO_COLOR: "1",
  };
  let failure;
  try {
    await run(process.execPath, [BIN, "artifact", "where", "pdf", "--json"], {
      env,
      timeout: 15_000,
    });
  } catch (error) {
    failure = error;
  }
  assert.ok(failure);
  assert.equal(failure.code, 1);
  const payload = JSON.parse(failure.stdout);
  assert.equal(payload.ok, false);
  assert.equal(payload.error, "no_continuity_record");
  assert.equal(failure.stderr, "");
});

for (const [name, fn] of tests) {
  try {
    await fn();
    passed++;
    process.stdout.write(`✓ ${name}\n`);
  } catch (error) {
    process.stderr.write(`✗ ${name}\n${error.stack || error}\n`);
    process.exitCode = 1;
  }
}
process.stdout.write(`${passed}/${tests.length} continuity receipt tests passed\n`);
