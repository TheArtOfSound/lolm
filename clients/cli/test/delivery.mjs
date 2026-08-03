// Copyright (c) 2026 Qira LLC. All rights reserved.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
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
