// Copyright (c) 2026 Qira LLC. All rights reserved.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import {
  CONTINUITY_SCHEMA,
  classifyContinuityQuestion,
  findContinuityRecord,
  listContinuityRecords,
  loadContinuityLedger,
  parseRunEvidence,
  recordContinuity,
  resolveContinuityQuestion,
} from "../lib/continuity.mjs";

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const BIN = join(here, "..", "bin", "lolm-delivery.mjs");
const MODULE = join(here, "..", "lib", "continuity.mjs");

let passed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

function sha256(body) {
  return createHash("sha256").update(body).digest("hex");
}

async function isolated(name) {
  const root = await mkdtemp(join(tmpdir(), `lolm-continuity-${name}-`));
  const ledger = join(root, "continuity.json");
  return { root, ledger, env: { ...process.env, LOLM_CONTINUITY_LEDGER: ledger, NO_COLOR: "1" } };
}

async function withLedger(ledger, fn) {
  const prior = process.env.LOLM_CONTINUITY_LEDGER;
  process.env.LOLM_CONTINUITY_LEDGER = ledger;
  try { return await fn(); }
  finally {
    if (prior == null) delete process.env.LOLM_CONTINUITY_LEDGER;
    else process.env.LOLM_CONTINUITY_LEDGER = prior;
  }
}

const referenceCases = [
  ...[
    "where is the PDF?", "where did you save the PDF?", "where did you put the PDF?",
    "what is the path to the PDF?", "which folder is the PDF in?", "find the PDF",
    "PDF location", "show me the PDF location", "where is the document?",
    "what directory contains the document?", "where did the report get saved?",
    "find the Word document", "where is the spreadsheet?", "where is the Excel file?",
    "what path has the CSV?", "where are the slides?", "where is the PowerPoint?",
    "find the presentation", "where is the image?", "which folder has the PNG?",
    "where is the JPEG?", "find the SVG", "where is the HTML?",
    "which directory contains the web page?", "where is the ZIP archive?",
  ].map((text) => [text, "where"]),
  ...[
    "open the PDF", "open that document", "show me the PDF", "launch the PDF",
    "open the Word document", "show me the report", "open the spreadsheet",
    "launch the Excel file", "open the CSV", "show me the slides",
    "open the PowerPoint", "launch the presentation", "open the image",
    "show me the PNG", "open the JPEG", "launch the SVG", "open the HTML",
    "show me the web page", "open the ZIP archive", "launch the artifact",
  ].map((text) => [text, "open"]),
  ...[
    "what did you create?", "what did you make?", "what did you generate?",
    "what was created?", "what was made?", "what was generated?",
    "which file did you create?", "which files did you create?",
    "which file did you make?", "which files did you make?",
    "what file was created?", "what files were created?",
    "what did you create as a PDF?", "what did you make as a document?",
    "what was generated as an image?",
  ].map((text) => [text, "created"]),
  ...[
    "did it deliver?", "did that deliver?", "did the file deliver?",
    "did the artifact deliver?", "did it save?", "did that save?",
    "did the file save?", "did it export?", "did that export?",
    "did it actually get delivered?", "did that actually get saved?",
    "did it actually get exported?", "was it delivered?", "was that saved?",
    "was the file exported?", "was the artifact delivered?",
    "did you actually deliver?", "did you actually save?", "did you actually export?",
    "was the PDF delivered?",
  ].map((text) => [text, "delivery"]),
  ...[
    ["what was the last task?", "task"], ["what is the last task?", "task"],
    ["show me the last task", "task"], ["previous task", "task"], ["prior task", "task"],
    ["what was the last run?", "run"], ["what is the previous run?", "run"],
    ["show the last run", "run"], ["previous run", "run"], ["prior run", "run"],
    ["what was the last receipt?", "receipt"], ["what is the previous receipt?", "receipt"],
    ["show me the last receipt", "receipt"], ["previous receipt", "receipt"],
    ["prior receipt", "receipt"], ["show the previous task", "task"],
    ["show me the previous run", "run"], ["show the previous receipt", "receipt"],
    ["last task", "task"], ["last receipt", "receipt"],
  ],
];

test("classifies at least 100 deterministic continuity phrasings", () => {
  assert.equal(referenceCases.length, 100);
  for (const [text, intent] of referenceCases) {
    const result = classifyContinuityQuestion(text);
    assert.ok(result, `unclassified: ${text}`);
    assert.equal(result.intent, intent, text);
  }
});

test("does not hijack ordinary informational questions", () => {
  for (const text of [
    "what is a PDF?", "explain file systems", "how does HTML work?",
    "tell me about the previous US election", "open source software is useful",
  ]) assert.equal(classifyContinuityQuestion(text), null, text);
});

test("extracts receipt, task, sandbox, run, session, manifest, and verdict evidence", () => {
  const receipt = "a".repeat(64);
  const manifest = "b".repeat(64);
  const parsed = parseRunEvidence(
    `sandbox sbx_deadbeef\nsession_id=sess_123456\nrun_id=run_123456\n` +
    `verdict shipped\nreceipt ${receipt}\nmanifest ${manifest}\ntask task_abcdef123\n`,
  );
  assert.deepEqual(parsed, {
    receipt_sha: receipt,
    manifest_sha: manifest,
    session_id: "sess_123456",
    run_id: "run_123456",
    task_id: "task_abcdef123",
    sandbox_id: "sbx_deadbeef",
    verdict: "shipped",
  });
});

test("records SHA-256 and reports a verified intact delivery", async () => {
  const ctx = await isolated("verified");
  const pdf = join(ctx.root, "output.pdf");
  const body = Buffer.from("%PDF-1.4\nverified\n%%EOF\n");
  await writeFile(pdf, body);
  await withLedger(ctx.ledger, async () => {
    await recordContinuity({
      task: "create a PDF", kind: "pdf", destination: ctx.root, files: [pdf],
      verified: true, delivered: true, receipt_sha: "c".repeat(64), task_id: "task_test",
      verdict: "shipped",
    });
    const record = await findContinuityRecord({ kind: "pdf" });
    assert.equal(record.fully_verified, true);
    assert.equal(record.artifacts[0].sha256, sha256(body));
    assert.equal(record.artifacts[0].integrity, "verified");
    const status = await resolveContinuityQuestion("was the PDF delivered?");
    assert.equal(status.ok, true);
    assert.match(status.message, /verified local artifact/);
  });
});

test("detects a modified local file and never calls it verified", async () => {
  const ctx = await isolated("changed");
  const pdf = join(ctx.root, "output.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\noriginal\n"));
  await withLedger(ctx.ledger, async () => {
    await recordContinuity({ task: "make PDF", kind: "pdf", destination: ctx.root, files: [pdf], verified: true, delivered: true, verdict: "shipped" });
    await writeFile(pdf, Buffer.from("%PDF-1.4\nchanged\n"));
    const record = await findContinuityRecord({ kind: "pdf" });
    assert.equal(record.artifacts[0].changed, true);
    assert.equal(record.artifacts[0].verified, false);
    const where = await resolveContinuityQuestion("where is the PDF?");
    assert.equal(where.ok, false);
    assert.match(where.message, /SHA-256 has changed/);
    const delivered = await resolveContinuityQuestion("was the PDF delivered?");
    assert.equal(delivered.ok, false);
    assert.match(delivered.message, /No longer verified/);
  });
});

test("detects a deleted local artifact", async () => {
  const ctx = await isolated("missing");
  const pdf = join(ctx.root, "output.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\n"));
  await withLedger(ctx.ledger, async () => {
    await recordContinuity({ task: "make PDF", kind: "pdf", destination: ctx.root, files: [pdf], verified: true, delivered: true, verdict: "shipped" });
    await rm(pdf);
    const where = await resolveContinuityQuestion("find the PDF");
    assert.equal(where.ok, false);
    assert.match(where.message, /missing/);
  });
});

test("migrates v1 paths without inventing SHA verification", async () => {
  const ctx = await isolated("migration");
  const pdf = join(ctx.root, "legacy.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\nlegacy\n"));
  await writeFile(ctx.ledger, JSON.stringify({
    schema: "lolm.delivery.ledger.v1",
    last: { task: "legacy", kind: "pdf", destination: ctx.root, files: [pdf], ts: 1 },
    deliveries: [{ task: "legacy", kind: "pdf", destination: ctx.root, files: [pdf], ts: 1 }],
  }));
  await withLedger(ctx.ledger, async () => {
    const ledger = await loadContinuityLedger();
    assert.equal(ledger.schema, CONTINUITY_SCHEMA);
    assert.equal(ledger.records.length, 1);
    const persisted = JSON.parse(await readFile(ctx.ledger, "utf8"));
    assert.equal(persisted.schema, CONTINUITY_SCHEMA);
    const record = await findContinuityRecord({ kind: "pdf" });
    assert.equal(record.artifacts[0].integrity, "legacy_unhashed");
    assert.equal(record.states.verified, false);
    const where = await resolveContinuityQuestion("where is the PDF?");
    assert.equal(where.ok, true);
    assert.equal(where.verified, false);
    const status = await resolveContinuityQuestion("was the PDF delivered?");
    assert.equal(status.ok, false);
    assert.match(status.message, /legacy delivery path/);
  });
});

test("fails closed on ambiguous pronouns when several records exist", async () => {
  const ctx = await isolated("ambiguous");
  const pdf = join(ctx.root, "one.pdf");
  const image = join(ctx.root, "two.png");
  await writeFile(pdf, Buffer.from("%PDF-1.4\n"));
  await writeFile(image, Buffer.from("PNG"));
  await withLedger(ctx.ledger, async () => {
    await recordContinuity({ task: "pdf", kind: "pdf", destination: ctx.root, files: [pdf], verified: true, delivered: true });
    await recordContinuity({ task: "image", kind: "image", destination: ctx.root, files: [image], verified: true, delivered: true });
    const result = await resolveContinuityQuestion("where is it?");
    assert.equal(result.code, 2);
    assert.equal(result.intent, "clarify");
  });
});

test("preserves all 30 simultaneous writers without corrupting JSON", async () => {
  const ctx = await isolated("concurrent");
  const jobs = [];
  for (let index = 0; index < 30; index++) {
    const file = join(ctx.root, `artifact-${index}.txt`);
    await writeFile(file, `artifact ${index}\n`);
    const script = [
      `import { recordContinuity } from ${JSON.stringify(`file://${MODULE}`)};`,
      `await recordContinuity({task:${JSON.stringify(`task ${index}`)},kind:'document',destination:${JSON.stringify(ctx.root)},files:[${JSON.stringify(file)}],verified:true,delivered:true,verdict:'shipped'});`,
    ].join("\n");
    jobs.push(run(process.execPath, ["--input-type=module", "--eval", script], { env: ctx.env }));
  }
  await Promise.all(jobs);
  await withLedger(ctx.ledger, async () => {
    const ledger = await loadContinuityLedger();
    assert.equal(ledger.records.length, 30);
    assert.equal(new Set(ledger.records.map((record) => record.task)).size, 30);
    JSON.parse(await readFile(ctx.ledger, "utf8"));
  });
});

test("100 local ask resolutions do not contact an invalid network origin", async () => {
  const ctx = await isolated("no-network");
  const pdf = join(ctx.root, "answer.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\nlocal\n"));
  await withLedger(ctx.ledger, async () => {
    await recordContinuity({
      task: "create the answer PDF", kind: "pdf", destination: ctx.root, files: [pdf],
      verified: true, delivered: true, receipt_sha: "d".repeat(64), task_id: "task_local",
      sandbox_id: "sbx_local", verdict: "shipped",
    });
  });
  const localCases = referenceCases.filter(([, intent]) => ["where", "created", "delivery", "task", "run", "receipt"].includes(intent));
  assert.ok(localCases.length >= 70);
  for (let index = 0; index < 100; index++) {
    const [question] = localCases[index % localCases.length];
    try {
      const result = await run(process.execPath, [BIN, "ask", question, "--base", "https://127.0.0.1.invalid"], { env: ctx.env, timeout: 10_000 });
      assert.doesNotMatch(result.stdout + result.stderr, /ENOTFOUND|ECONN|fetch failed|network/i, question);
    } catch (error) {
      assert.doesNotMatch(String(error.stdout || "") + String(error.stderr || ""), /ENOTFOUND|ECONN|fetch failed|network/i, question);
      assert.ok([1, 2].includes(error.code), `unexpected exit for ${question}: ${error.code}`);
    }
  }
});

test("artifact list, where, and inspect provide machine-readable local state", async () => {
  const ctx = await isolated("commands");
  const pdf = join(ctx.root, "command.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\ncommand\n"));
  await withLedger(ctx.ledger, async () => {
    await recordContinuity({ task: "command task", kind: "pdf", destination: ctx.root, files: [pdf], verified: true, delivered: true, receipt_sha: "e".repeat(64), verdict: "shipped" });
  });
  for (const args of [
    ["artifact", "list", "pdf", "--json"],
    ["artifact", "where", "pdf", "--json"],
    ["artifact", "inspect", "pdf", "--json"],
  ]) {
    const result = await run(process.execPath, [BIN, ...args], { env: ctx.env });
    const parsed = JSON.parse(result.stdout);
    assert.equal(parsed.ok, true, args.join(" "));
    assert.doesNotMatch(result.stderr, /./);
  }
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
process.stdout.write(`${passed}/${tests.length} continuity tests passed\n`);
