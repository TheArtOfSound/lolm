// Copyright (c) 2026 Qira LLC. All rights reserved.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import {
  artifactLocationQuestion,
  commandTask,
  isOfficialCredentialFabrication,
  loadLastDelivery,
  recordDelivery,
  requestedArtifactKind,
  selectDeliveredArtifacts,
} from "../lib/delivery.mjs";

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const BIN = join(here, "..", "bin", "lolm-delivery.mjs");

let passed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("extracts a code task while skipping flags", () => {
  const parsed = commandTask([
    "--base", "https://example.com", "code", "make", "a", "PDF", "--max-steps", "10",
  ]);
  assert.equal(parsed.command, "code");
  assert.equal(parsed.task, "make a PDF");
});

test("recognizes PDF and document artifact requests", () => {
  assert.equal(requestedArtifactKind("make a PDF report"), "pdf");
  assert.equal(requestedArtifactKind("create a document"), "document");
  assert.equal(requestedArtifactKind("fix parser.py"), "");
});

test("blocks fabricated official attendance proof but permits labeled self-attestation", () => {
  assert.equal(isOfficialCredentialFabrication(
    "make a pdf proving I attend ASU and fill in the rest",
  ), true);
  assert.equal(isOfficialCredentialFabrication(
    "make a clearly labeled unofficial self-attestation that I attend ASU",
  ), false);
});

test("recognizes cross-command artifact location follow-ups", () => {
  assert.equal(artifactLocationQuestion("where is the PDF?"), true);
  assert.equal(artifactLocationQuestion("open that document"), true);
  assert.equal(artifactLocationQuestion("what is a PDF?"), false);
});

test("delivery ledger returns only existing local files", async () => {
  const root = await mkdtemp(join(tmpdir(), "lolm-delivery-test-"));
  const dir = join(root, "out");
  await mkdir(dir);
  const pdf = join(dir, "output.pdf");
  const source = join(dir, "main.py");
  await writeFile(pdf, Buffer.from("%PDF-1.4\n"));
  await writeFile(source, "print('x')\n");
  process.env.LOLM_DELIVERY_LEDGER = join(root, "deliveries.json");
  await recordDelivery({ task: "make pdf", kind: "pdf", destination: dir, files: [pdf] });
  const last = await loadLastDelivery();
  assert.equal(last.exists, true);
  assert.deepEqual(last.files, [pdf]);
  assert.deepEqual(selectDeliveredArtifacts([source, pdf], "pdf"), [pdf]);
});

test("launcher reports the published beta.2 version", async () => {
  const result = await run(process.execPath, [BIN, "--version"], {
    env: { ...process.env, NO_COLOR: "1" },
  });
  assert.equal(result.stdout.trim(), "0.3.0-beta.2");
  assert.equal(result.stderr, "");
});

test("launcher blocks credential fabrication before any remote request", async () => {
  await assert.rejects(
    run(process.execPath, [
      BIN, "code", "make a PDF proving I attend ASU and fill in the rest",
      "--base", "https://127.0.0.1.invalid",
    ], { env: { ...process.env, NO_COLOR: "1" } }),
    (error) => {
      assert.equal(error.code, 2);
      assert.match(error.stderr, /cannot fabricate official proof/i);
      assert.doesNotMatch(error.stderr, /fetch|network|ENOTFOUND/i);
      return true;
    },
  );
});

test("ask where is the PDF resolves from the local delivery ledger without a model call", async () => {
  const root = await mkdtemp(join(tmpdir(), "lolm-delivery-followup-"));
  const pdf = join(root, "answer.pdf");
  const ledger = join(root, "deliveries.json");
  await writeFile(pdf, Buffer.from("%PDF-1.4\n"));
  const env = { ...process.env, LOLM_DELIVERY_LEDGER: ledger, NO_COLOR: "1" };
  const prior = process.env.LOLM_DELIVERY_LEDGER;
  process.env.LOLM_DELIVERY_LEDGER = ledger;
  await recordDelivery({ task: "make pdf", kind: "pdf", destination: root, files: [pdf] });
  if (prior == null) delete process.env.LOLM_DELIVERY_LEDGER;
  else process.env.LOLM_DELIVERY_LEDGER = prior;
  const result = await run(process.execPath, [
    BIN, "ask", "where is the PDF?", "--base", "https://127.0.0.1.invalid",
  ], { env });
  assert.equal(result.stdout.trim(), pdf);
  assert.equal(result.stderr, "");
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
process.stdout.write(`${passed}/${tests.length} delivery tests passed\n`);
